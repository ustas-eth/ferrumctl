from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import websockets

from .constants import CLIENT_VERSION, MAX_WEBSOCKET_MESSAGE_BYTES
from .errors import WakeDeferred, WakectlError


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
            max_size=MAX_WEBSOCKET_MESSAGE_BYTES,
            user_agent_header=None,
        )
    parsed = urlparse(endpoint)
    if parsed.scheme != "ws":
        raise WakectlError("endpoint must be unix://, unix://PATH, or ws://HOST:PORT")
    return await websockets.connect(
        endpoint,
        compression=None,
        max_size=MAX_WEBSOCKET_MESSAGE_BYTES,
        user_agent_header=None,
    )


def resolve_unix_endpoint(endpoint: str) -> str:
    raw = endpoint.removeprefix("unix://")
    if not raw:
        path = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        path = path / "app-server-control" / "app-server-control.sock"
    else:
        path = Path(raw)
    path = path.expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return str(path.resolve())


def normalize_endpoint(endpoint: str) -> str:
    if endpoint.startswith("unix://"):
        return "unix://" + resolve_unix_endpoint(endpoint)
    parsed = urlparse(endpoint)
    if parsed.scheme != "ws":
        raise WakectlError("endpoint must be unix://, unix://PATH, or ws://HOST:PORT")
    return endpoint


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


async def read_thread(app: AppServer, thread_id: str) -> dict[str, Any]:
    result = await app.request(
        "thread/read",
        {"threadId": thread_id, "includeTurns": False},
    )
    return result["thread"]


async def get_thread_status(app: AppServer, thread_id: str) -> dict[str, Any]:
    thread = await read_thread(app, thread_id)
    return thread.get("status", {"type": "unknown"})


async def list_thread_turns(
    app: AppServer,
    thread_id: str,
    *,
    limit: int = 1,
    items_view: str = "notLoaded",
) -> list[dict[str, Any]]:
    result = await app.request(
        "thread/turns/list",
        {
            "threadId": thread_id,
            "limit": limit,
            "sortDirection": "desc",
            "itemsView": items_view,
        },
    )
    return result.get("data", [])


def status_name(status: dict[str, Any]) -> str:
    return str(status.get("type", "unknown"))


async def send_turn(
    app: AppServer,
    thread_id: str,
    message: str,
    *,
    allow_active: bool = False,
) -> dict[str, Any]:
    loaded = await list_loaded(app)
    if thread_id not in loaded:
        raise WakeDeferred(f"thread is not loaded on this app-server: {thread_id}")
    status = await get_thread_status(app, thread_id)
    name = status_name(status)
    if name == "active":
        if not allow_active:
            raise WakeDeferred("thread is active; refusing to send without --allow-active")
    elif name == "notLoaded":
        raise WakeDeferred("thread is not loaded")
    elif name != "idle":
        raise WakectlError(f"thread status is {name}; refusing to send")
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
