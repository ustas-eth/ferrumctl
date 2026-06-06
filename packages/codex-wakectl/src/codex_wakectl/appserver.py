from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import websockets

from .constants import CLIENT_VERSION
from .errors import WakectlError


class AppServer:
    def __init__(self, endpoint: str, timeout: float):
        self.endpoint = endpoint
        self.timeout = timeout
        self.next_id = 1
        self.ws: Any = None

    async def __aenter__(self) -> "AppServer":
        self.ws = await connect_websocket(self.endpoint)
        try:
            await self.request(
                "initialize",
                {
                    "clientInfo": {
                        "name": "codex_wakectl",
                        "title": "codex-wakectl",
                        "version": CLIENT_VERSION,
                    },
                    "capabilities": {"experimentalApi": True},
                },
            )
            await self.notify("initialized", {})
        except Exception:
            ws = self.ws
            self.ws = None
            if ws is not None:
                try:
                    await ws.close()
                except Exception:
                    pass
            raise
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self.ws is not None:
            await self.ws.close()

    async def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        request_id = self.next_id
        self.next_id += 1
        msg: dict[str, Any] = {"method": method, "id": request_id}
        if params is not None:
            msg["params"] = params
        await self.ws.send(json.dumps(msg, separators=(",", ":")))
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=0.2)
            except TimeoutError:
                continue
            msg = json.loads(raw)
            if msg.get("id") != request_id:
                continue
            if "error" in msg:
                raise WakectlError(json.dumps(msg["error"], separators=(",", ":")))
            return msg.get("result")
        raise WakectlError(f"timed out waiting for app-server method {method}")

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        msg: dict[str, Any] = {"method": method}
        if params is not None:
            msg["params"] = params
        await self.ws.send(json.dumps(msg, separators=(",", ":")))


async def connect_websocket(endpoint: str) -> Any:
    if endpoint.startswith("unix://"):
        socket_path = resolve_unix_endpoint(endpoint)
        return await websockets.unix_connect(
            socket_path,
            uri="ws://localhost/rpc",
            compression=None,
            user_agent_header=None,
        )
    parsed = urlparse(endpoint)
    if parsed.scheme != "ws":
        raise WakectlError("endpoint must be unix://, unix://PATH, or ws://HOST:PORT")
    return await websockets.connect(
        endpoint,
        compression=None,
        user_agent_header=None,
    )


def resolve_unix_endpoint(endpoint: str) -> str:
    raw = endpoint.removeprefix("unix://")
    if not raw:
        codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        return str(codex_home / "app-server-control" / "app-server-control.sock")
    path = Path(raw)
    if not path.is_absolute():
        path = Path.cwd() / path
    return str(path)


async def list_loaded(app: AppServer) -> list[str]:
    ids: list[str] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {}
        if cursor is not None:
            params["cursor"] = cursor
        result = await app.request("thread/loaded/list", params)
        ids.extend(result.get("data", []))
        cursor = result.get("nextCursor")
        if cursor is None:
            return ids


async def get_thread_status(app: AppServer, thread_id: str) -> dict[str, Any]:
    result = await app.request(
        "thread/read",
        {"threadId": thread_id, "includeTurns": False},
    )
    return result["thread"].get("status", {"type": "unknown"})


def status_name(status: dict[str, Any]) -> str:
    return str(status.get("type", "unknown"))


def thread_is_active(status: dict[str, Any]) -> bool:
    return status_name(status) not in {"idle", "unknown"}


async def send_turn(
    app: AppServer,
    thread_id: str,
    message: str,
    *,
    allow_active: bool = False,
) -> dict[str, Any]:
    loaded = await list_loaded(app)
    if thread_id not in loaded:
        raise WakectlError(f"thread is not loaded on this app-server: {thread_id}")
    status = await get_thread_status(app, thread_id)
    name = status_name(status)
    if name != "idle" and not allow_active:
        raise WakectlError(f"thread is {name}; refusing to start overlapping turn")
    result = await app.request(
        "turn/start",
        {
            "threadId": thread_id,
            "input": [
                {
                    "type": "text",
                    "text": message,
                    "textElements": [],
                }
            ],
        },
    )
    return result["turn"]


async def get_goal(app: AppServer, thread_id: str) -> dict[str, Any] | None:
    result = await app.request("thread/goal/get", {"threadId": thread_id})
    return result.get("goal")
