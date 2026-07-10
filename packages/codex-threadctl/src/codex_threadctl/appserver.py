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
from .errors import ThreadctlError


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
                        "name": "codex_threadctl",
                        "title": "codex-threadctl",
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
        message: dict[str, Any] = {"method": method, "id": request_id}
        if params is not None:
            message["params"] = params
        await self.ws.send(json.dumps(message, separators=(",", ":")))

        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=0.2)
            except TimeoutError:
                continue
            response = json.loads(raw)
            if response.get("id") != request_id:
                continue
            if "error" in response:
                raise ThreadctlError(json.dumps(response["error"], separators=(",", ":")))
            return response.get("result")
        raise ThreadctlError(f"timed out waiting for app-server method {method}")

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        message: dict[str, Any] = {"method": method}
        if params is not None:
            message["params"] = params
        await self.ws.send(json.dumps(message, separators=(",", ":")))


async def connect_websocket(endpoint: str) -> Any:
    if endpoint.startswith("unix://"):
        return await websockets.unix_connect(
            resolve_unix_endpoint(endpoint),
            uri="ws://localhost/rpc",
            compression=None,
            max_size=MAX_WEBSOCKET_MESSAGE_BYTES,
            user_agent_header=None,
        )
    parsed = urlparse(endpoint)
    if parsed.scheme != "ws":
        raise ThreadctlError("endpoint must be unix://, unix://PATH, or ws://HOST:PORT")
    return await websockets.connect(
        endpoint,
        compression=None,
        max_size=MAX_WEBSOCKET_MESSAGE_BYTES,
        user_agent_header=None,
    )


def resolve_unix_endpoint(endpoint: str) -> str:
    raw = endpoint.removeprefix("unix://")
    if raw:
        path = Path(raw)
    else:
        path = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        path = path / "app-server-control" / "app-server-control.sock"
    path = path.expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return str(path.resolve())


async def list_loaded(app: AppServer) -> list[str]:
    thread_ids: list[str] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {}
        if cursor is not None:
            params["cursor"] = cursor
        result = await app.request("thread/loaded/list", params)
        thread_ids.extend(result.get("data", []))
        cursor = result.get("nextCursor")
        if cursor is None:
            return thread_ids


async def read_thread(app: AppServer, thread_id: str) -> dict[str, Any]:
    result = await app.request(
        "thread/read",
        {"threadId": thread_id, "includeTurns": False},
    )
    return result["thread"]


async def list_turn_page(
    app: AppServer,
    thread_id: str,
    *,
    cursor: str | None = None,
    limit: int = 20,
    sort_direction: str = "desc",
    items_view: str = "summary",
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "threadId": thread_id,
        "limit": limit,
        "sortDirection": sort_direction,
        "itemsView": items_view,
    }
    if cursor is not None:
        params["cursor"] = cursor
    return await app.request("thread/turns/list", params)


async def get_goal(app: AppServer, thread_id: str) -> dict[str, Any] | None:
    result = await app.request("thread/goal/get", {"threadId": thread_id})
    return result.get("goal")


def status_name(thread: dict[str, Any]) -> str:
    status = thread.get("status", {})
    return str(status.get("type", "unknown"))


async def interrupt_thread(app: AppServer, thread_id: str) -> dict[str, Any]:
    if thread_id not in await list_loaded(app):
        raise ThreadctlError(f"thread is not loaded on this app-server: {thread_id}")

    thread = await read_thread(app, thread_id)
    if status_name(thread) != "active":
        raise ThreadctlError(f"thread is {status_name(thread)}; no active turn to interrupt")

    page = await list_turn_page(
        app,
        thread_id,
        limit=1,
        items_view="notLoaded",
    )
    turn = next(iter(page.get("data", [])), None)
    if turn is None or turn.get("status") != "inProgress" or not turn.get("id"):
        raise ThreadctlError("active turn id is unavailable; inspect the thread and retry")

    await app.request(
        "turn/interrupt",
        {"threadId": thread_id, "turnId": turn["id"]},
    )
    return {"threadId": thread_id, "turnId": turn["id"], "status": "interrupted"}


async def compact_thread(app: AppServer, thread_id: str) -> dict[str, Any]:
    if thread_id not in await list_loaded(app):
        raise ThreadctlError(f"thread is not loaded on this app-server: {thread_id}")

    thread = await read_thread(app, thread_id)
    name = status_name(thread)
    if name == "active":
        raise ThreadctlError("thread is active; manual compaction would replace its turn")
    if name != "idle":
        raise ThreadctlError(f"thread status is {name}; refusing to compact")

    goal = await get_goal(app, thread_id)
    if goal is not None and goal.get("status") == "active":
        raise ThreadctlError("thread goal is active; pause it before manual compaction")

    await app.request("thread/compact/start", {"threadId": thread_id})
    return {"threadId": thread_id, "status": "started"}
