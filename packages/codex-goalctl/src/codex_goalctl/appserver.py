from __future__ import annotations

import argparse
import json
import selectors
import subprocess
import time
from typing import Any

from .errors import GoalctlError


CLIENT_VERSION = "0.1.0"


class AppServer:
    def __init__(self, codex_bin: str, timeout: float):
        self.timeout = timeout
        try:
            self.proc = subprocess.Popen(
                [codex_bin, "app-server", "--listen", "stdio://"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            raise GoalctlError(f"failed to start {codex_bin!r}: {exc}") from exc
        self.sel = selectors.DefaultSelector()
        self.sel.register(self.proc.stdout, selectors.EVENT_READ, "stdout")
        self.sel.register(self.proc.stderr, selectors.EVENT_READ, "stderr")
        self.stderr_tail: list[str] = []
        self.next_id = 1

    def close(self) -> None:
        if self.proc.poll() is not None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=2)

    def send(self, msg: dict[str, Any]) -> None:
        if self.proc.stdin is None:
            raise GoalctlError("app-server stdin is unavailable")
        self.proc.stdin.write(json.dumps(msg, separators=(",", ":")) + "\n")
        self.proc.stdin.flush()

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
            if self.proc.poll() is not None:
                raise GoalctlError(self.format_error("app-server exited"))
            for key, _ in self.sel.select(timeout=0.2):
                line = key.fileobj.readline()
                if not line:
                    continue
                if key.data == "stderr":
                    self.stderr_tail.append(line.rstrip())
                    self.stderr_tail = self.stderr_tail[-20:]
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise GoalctlError(f"invalid app-server JSON: {line.rstrip()}") from exc
                if msg.get("id") != request_id:
                    continue
                if "error" in msg:
                    raise GoalctlError(json.dumps(msg["error"], separators=(",", ":")))
                return msg.get("result")
        raise GoalctlError(self.format_error("timed out waiting for app-server"))

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
