from __future__ import annotations

import argparse
import json
import os
import selectors
import subprocess
import time
from typing import Any, IO

from .errors import GoalctlError


CLIENT_VERSION = "0.1.5"


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
            raise GoalctlError(f"failed to start {codex_bin!r}: {exc}") from exc
        if self.proc.stdin is None or self.proc.stdout is None or self.proc.stderr is None:
            self.proc.kill()
            self.proc.wait()
            raise GoalctlError("app-server pipes are unavailable")
        self.stdin: IO[bytes] = self.proc.stdin
        self.stdout: IO[bytes] = self.proc.stdout
        self.stderr: IO[bytes] = self.proc.stderr
        self.sel = selectors.DefaultSelector()
        self.sel.register(self.stdout, selectors.EVENT_READ, "stdout")
        self.sel.register(self.stderr, selectors.EVENT_READ, "stderr")
        self.read_buffers = {"stdout": bytearray(), "stderr": bytearray()}
        self.stderr_tail: list[str] = []
        self.next_id = 1

    def close(self) -> None:
        try:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait(timeout=2)
        finally:
            self.sel.close()
            self.stdin.close()
            self.stdout.close()
            self.stderr.close()

    def send(self, msg: dict[str, Any]) -> None:
        line = json.dumps(msg, separators=(",", ":")) + "\n"
        self.stdin.write(line.encode())
        self.stdin.flush()

    def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        request_id = self.next_id
        self.next_id += 1
        msg: dict[str, Any] = {"method": method, "id": request_id}
        if params is not None:
            msg["params"] = params
        self.send(msg)
        return self.wait_for(request_id)

    def notify(self, method: str) -> None:
        self.send({"method": method})

    def wait_for(self, request_id: int) -> Any:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            while (line := self.pop_line("stderr")) is not None:
                self.stderr_tail.append(line.decode(errors="replace"))
                self.stderr_tail = self.stderr_tail[-20:]

            while (line := self.pop_line("stdout")) is not None:
                try:
                    msg = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    raise GoalctlError(
                        f"invalid app-server JSON: {line.decode(errors='replace')}"
                    ) from exc
                if not isinstance(msg, dict):
                    raise GoalctlError("app-server returned a non-object message")
                if "method" in msg:
                    continue
                if msg.get("id") != request_id:
                    continue
                if "error" in msg:
                    raise GoalctlError(json.dumps(msg["error"], separators=(",", ":")))
                if "result" not in msg:
                    raise GoalctlError("app-server response has no result")
                return msg["result"]

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            events = self.sel.select(timeout=min(0.2, remaining))
            for key, _ in events:
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    self.sel.unregister(key.fileobj)
                    continue
                self.read_buffers[key.data].extend(chunk)
            if not events and self.proc.poll() is not None:
                raise GoalctlError(self.format_error("app-server exited"))
        raise GoalctlError(self.format_error("timed out waiting for app-server"))

    def pop_line(self, stream: str) -> bytes | None:
        buffer = self.read_buffers[stream]
        newline = buffer.find(b"\n")
        if newline < 0:
            return None
        line = bytes(buffer[:newline])
        del buffer[: newline + 1]
        return line

    def format_error(self, message: str) -> str:
        if not self.stderr_tail:
            return message
        return message + "\n" + "\n".join(self.stderr_tail)


def appserver_request(args: argparse.Namespace, method: str, params: dict[str, Any]) -> Any:
    app = connect_appserver(args)
    try:
        return app.request(method, params)
    finally:
        app.close()


def connect_appserver(args: argparse.Namespace) -> AppServer:
    app = AppServer(args.codex_bin, args.timeout)
    try:
        app.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "codex_goalctl",
                    "title": "codex-goalctl",
                    "version": CLIENT_VERSION,
                }
            },
        )
        app.notify("initialized")
        return app
    except Exception:
        app.close()
        raise
