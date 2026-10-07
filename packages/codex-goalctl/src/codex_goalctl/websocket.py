from __future__ import annotations

import errno
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from websockets.exceptions import WebSocketException
from websockets.sync.client import connect, unix_connect

from .appserver import RpcConnection
from .errors import GoalctlError, ServerUnavailable


class WebSocketAppServer(RpcConnection):
    def __init__(self, endpoint: str, timeout: float):
        self.timeout = timeout
        self.next_id = 1
        options = {
            "open_timeout": timeout,
            "close_timeout": 2,
            "compression": None,
            "user_agent_header": None,
            "max_size": 16 * 1024 * 1024,
        }
        try:
            if endpoint.startswith("unix://"):
                raw = endpoint.removeprefix("unix://")
                path = Path(raw) if raw else Path(
                    os.environ.get("CODEX_HOME", Path.home() / ".codex")
                ) / "app-server-control" / "app-server-control.sock"
                self.ws = unix_connect(str(path.expanduser().resolve()), **options)
            elif urlparse(endpoint).scheme in {"ws", "wss"}:
                self.ws = connect(endpoint, **options)
            else:
                raise GoalctlError(
                    "endpoint must be unix://, unix://PATH, ws://HOST:PORT, or wss://HOST:PORT"
                )
        except (OSError, TimeoutError, WebSocketException) as exc:
            if isinstance(exc, OSError) and exc.errno in {errno.ENOENT, errno.ECONNREFUSED}:
                raise ServerUnavailable(f"could not connect to app-server: {exc}") from exc
            raise GoalctlError(f"could not connect to app-server: {exc}") from exc

    def send(self, msg: dict[str, Any]) -> None:
        try:
            self.ws.send(json.dumps(msg, separators=(",", ":")))
        except (OSError, WebSocketException) as exc:
            raise GoalctlError(f"app-server connection failed: {exc}") from exc

    def wait_for(self, request_id: int) -> Any:
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise GoalctlError("timed out waiting for app-server")
            try:
                line = self.ws.recv(timeout=remaining)
            except TimeoutError as exc:
                raise GoalctlError("timed out waiting for app-server") from exc
            except (OSError, WebSocketException) as exc:
                raise GoalctlError(f"app-server connection failed: {exc}") from exc
            msg = self.parse_response(line, request_id)
            if msg is not None:
                return msg["result"]

    def close(self) -> None:
        self.ws.close()
