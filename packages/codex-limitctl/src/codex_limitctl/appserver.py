from __future__ import annotations

import json
import os
import selectors
import subprocess
import time
from typing import Any, IO

from . import __version__
from .errors import LimitctlError


class AppServer:
    def __init__(self, codex_bin: str, timeout: float):
        self.timeout = timeout
        try:
            self.proc = subprocess.Popen(
                [codex_bin, "app-server", "--listen", "stdio://"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except OSError as exc:
            raise LimitctlError(f"failed to start {codex_bin!r}: {exc}") from exc
        if self.proc.stdin is None or self.proc.stdout is None or self.proc.stderr is None:
            self.proc.kill()
            self.proc.wait()
            raise LimitctlError("app-server pipes are unavailable")
        self.stdin: IO[bytes] = self.proc.stdin
        self.stdout: IO[bytes] = self.proc.stdout
        self.stderr: IO[bytes] = self.proc.stderr
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.stdout, selectors.EVENT_READ, "stdout")
        self.selector.register(self.stderr, selectors.EVENT_READ, "stderr")
        self.buffers = {"stdout": bytearray(), "stderr": bytearray()}
        self.saw_stderr = False
        self.next_id = 1

    def close(self) -> None:
        try:
            if self.proc.poll() is None:
                try:
                    self.proc.terminate()
                    try:
                        self.proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        self.proc.kill()
                        self.proc.wait(timeout=2)
                except OSError:
                    pass
        finally:
            self.selector.close()
            for stream in (self.stdin, self.stdout, self.stderr):
                try:
                    stream.close()
                except OSError:
                    pass

    def send(self, message: dict[str, Any]) -> None:
        line = json.dumps(message, separators=(",", ":")) + "\n"
        try:
            self.stdin.write(line.encode())
            self.stdin.flush()
        except OSError as exc:
            raise LimitctlError("failed to write to app-server") from exc

    def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> Any:
        request_id = self.next_id
        self.next_id += 1
        message: dict[str, Any] = {"method": method, "id": request_id}
        if params is not None:
            message["params"] = params
        self.send(message)
        effective_timeout = self.timeout if timeout is None else timeout
        return self.wait_for(request_id, method, effective_timeout)

    def notify(self, method: str) -> None:
        self.send({"method": method})

    def wait_for(self, request_id: int, method: str, timeout: float) -> Any:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            while (line := self.pop_line("stderr")) is not None:
                self.saw_stderr = True

            while (line := self.pop_line("stdout")) is not None:
                try:
                    message = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    raise LimitctlError("app-server returned invalid JSON") from exc
                if not isinstance(message, dict):
                    raise LimitctlError("app-server returned a non-object message")
                if "method" in message or message.get("id") != request_id:
                    continue
                if "error" in message:
                    raise LimitctlError(format_rpc_error(message["error"]))
                if "result" not in message:
                    raise LimitctlError(f"app-server method {method} returned no result")
                return message["result"]

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                events = self.selector.select(timeout=min(0.2, remaining))
                for key, _ in events:
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        self.selector.unregister(key.fileobj)
                        continue
                    self.buffers[key.data].extend(chunk)
            except OSError as exc:
                raise LimitctlError("failed to read from app-server") from exc
            if not events and self.proc.poll() is not None:
                status = self.proc.returncode
                raise LimitctlError(
                    self.format_error(f"app-server exited with status {status}")
                )
        raise LimitctlError(
            self.format_error(f"timed out after {timeout:g}s waiting for {method}")
        )

    def pop_line(self, stream: str) -> bytes | None:
        buffer = self.buffers[stream]
        newline = buffer.find(b"\n")
        if newline < 0:
            return None
        line = bytes(buffer[:newline])
        del buffer[: newline + 1]
        return line

    def format_error(self, message: str) -> str:
        suffix = " (app-server diagnostics omitted)" if self.saw_stderr else ""
        return message + suffix


def format_rpc_error(value: Any) -> str:
    if not isinstance(value, dict):
        return "app-server request failed"
    code = value.get("code")
    if isinstance(code, bool) or not isinstance(code, int):
        code = None
    message = value.get("message")
    if not isinstance(message, str):
        message = "request failed"
    message = "".join(character if character.isprintable() else " " for character in message)
    message = " ".join(message.split())[:300] or "request failed"
    prefix = f"app-server error {code}" if code is not None else "app-server error"
    return f"{prefix}: {message}"


def read_account(codex_bin: str, timeout: float, method: str) -> Any:
    deadline = time.monotonic() + timeout
    app = AppServer(codex_bin, timeout)

    def remaining(method: str) -> float:
        value = deadline - time.monotonic()
        if value <= 0:
            raise LimitctlError(f"timed out after {timeout:g}s waiting for {method}")
        return value

    try:
        app.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "codex_limitctl",
                    "title": "codex-limitctl",
                    "version": __version__,
                }
            },
            timeout=remaining("initialize"),
        )
        app.notify("initialized")
        return app.request(method, timeout=remaining(method))
    finally:
        app.close()


def read_rate_limits(codex_bin: str, timeout: float) -> Any:
    return read_account(codex_bin, timeout, "account/rateLimits/read")


def read_token_usage(codex_bin: str, timeout: float) -> Any:
    return read_account(codex_bin, timeout, "account/usage/read")
