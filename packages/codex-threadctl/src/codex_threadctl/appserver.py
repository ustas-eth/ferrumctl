from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import websockets

from .constants import CLIENT_VERSION, MAX_WEBSOCKET_MESSAGE_BYTES
from .errors import (
    AppServerResponseError,
    DeliveryUncertain,
    DirectInputUnsupported,
    ThreadctlError,
    ThreadNotLoaded,
    ThreadStateError,
)

TRACKED_NOTIFICATIONS = {
    "turn/started",
    "item/started",
    "item/completed",
    "error",
}

DIRECT_INPUT_TO_V2_SUBAGENT = (
    "direct app-server input is not allowed for multi-agent v2 sub-agents"
)
PARENT_OWNED_INPUT_ERROR = (
    "thread is controlled by its native parent; direct start, steer, and wake "
    "are unavailable"
)


class AppServer:
    def __init__(
        self,
        endpoint: str,
        timeout: float,
        *,
        client_name: str = "codex_threadctl",
        client_title: str = "codex-threadctl",
        client_version: str = CLIENT_VERSION,
    ):
        self.endpoint = normalize_endpoint(endpoint)
        self.timeout = timeout
        self.client_name = client_name
        self.client_title = client_title
        self.client_version = client_version
        self.next_id = 1
        self.ws: Any = None
        self.server_info: dict[str, Any] = {}
        self.turn_notifications: list[dict[str, Any]] = []

    async def __aenter__(self) -> "AppServer":
        try:
            self.ws = await connect_websocket(self.endpoint)
            result = await self.request(
                "initialize",
                {
                    "clientInfo": {
                        "name": self.client_name,
                        "title": self.client_title,
                        "version": self.client_version,
                    },
                    "capabilities": {"experimentalApi": True},
                },
            )
            self.server_info = require_object(result, "initialize result")
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
        if self.ws is None:
            raise ThreadctlError("app-server connection is not open")
        request_id = self.next_id
        self.next_id += 1
        message: dict[str, Any] = {"method": method, "id": request_id}
        if params is not None:
            message["params"] = params
        await self.ws.send(json.dumps(message, separators=(",", ":")))

        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                message = (
                    f"timed out after {self.timeout:g}s waiting for "
                    f"app-server method {method}"
                )
                if method == "thread/turns/list":
                    message += (
                        "; long histories or concurrent readers may need a larger --timeout"
                    )
                raise ThreadctlError(message)
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=min(0.2, remaining))
            except TimeoutError:
                continue
            try:
                response = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise ThreadctlError("app-server returned invalid JSON") from exc
            if not isinstance(response, dict):
                raise ThreadctlError("app-server returned a non-object message")
            if "method" in response:
                if (
                    "id" not in response
                    and response.get("method") in TRACKED_NOTIFICATIONS
                ):
                    self.turn_notifications.append(response)
                continue
            if response.get("id") != request_id:
                continue
            if "error" in response:
                raise AppServerResponseError(response["error"])
            if "result" not in response:
                raise ThreadctlError(f"app-server method {method} returned no result")
            return response["result"]

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        if self.ws is None:
            raise ThreadctlError("app-server connection is not open")
        message: dict[str, Any] = {"method": method}
        if params is not None:
            message["params"] = params
        await self.ws.send(json.dumps(message, separators=(",", ":")))


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ThreadctlError(f"app-server returned invalid {label}")
    return value


def unsupported_method(error: AppServerResponseError) -> bool:
    payload = error.payload
    code = payload.get("code") if isinstance(payload, dict) else None
    message = str(error).lower()
    return code == -32601 or "not supported" in message or "method not found" in message


async def connect_websocket(endpoint: str) -> Any:
    try:
        if endpoint.startswith("unix://"):
            return await websockets.unix_connect(
                resolve_unix_endpoint(endpoint),
                uri="ws://localhost/rpc",
                compression=None,
                max_size=MAX_WEBSOCKET_MESSAGE_BYTES,
                user_agent_header=None,
            )
        return await websockets.connect(
            endpoint,
            compression=None,
            max_size=MAX_WEBSOCKET_MESSAGE_BYTES,
            user_agent_header=None,
        )
    except (OSError, websockets.WebSocketException) as exc:
        raise ThreadctlError(f"could not connect to app-server: {exc}") from exc


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


def normalize_endpoint(endpoint: str) -> str:
    if endpoint.startswith("unix://"):
        return "unix://" + resolve_unix_endpoint(endpoint)
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"ws", "wss"}:
        raise ThreadctlError(
            "endpoint must be unix://, unix://PATH, ws://HOST:PORT, or wss://HOST:PORT"
        )
    return endpoint


async def list_loaded(app: AppServer) -> list[str]:
    thread_ids: list[str] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    while True:
        params: dict[str, Any] = {}
        if cursor is not None:
            params["cursor"] = cursor
        result = require_object(
            await app.request("thread/loaded/list", params),
            "thread/loaded/list result",
        )
        data = result.get("data")
        if not isinstance(data, list) or not all(isinstance(item, str) for item in data):
            raise ThreadctlError("app-server returned invalid loaded thread data")
        thread_ids.extend(data)
        next_cursor = result.get("nextCursor")
        if next_cursor is None:
            return thread_ids
        if not isinstance(next_cursor, str) or next_cursor in seen_cursors:
            raise ThreadctlError("app-server returned an invalid loaded-thread cursor")
        seen_cursors.add(next_cursor)
        cursor = next_cursor


async def list_threads(
    app: AppServer,
    *,
    parent_thread_id: str | None = None,
    ancestor_thread_id: str | None = None,
    limit: int = 20,
    sort_key: str = "recency_at",
) -> list[dict[str, Any]]:
    if parent_thread_id is not None and ancestor_thread_id is not None:
        raise ThreadctlError("parent and ancestor filters are mutually exclusive")
    if limit < 0:
        raise ThreadctlError("thread list limit must be zero or greater")

    threads: list[dict[str, Any]] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    while limit == 0 or len(threads) < limit:
        remaining = limit - len(threads) if limit else 100
        params: dict[str, Any] = {
            "limit": min(remaining, 100),
            "sortKey": sort_key,
            "sortDirection": "desc",
            "modelProviders": [],
        }
        if cursor is not None:
            params["cursor"] = cursor
        if parent_thread_id is not None:
            params["parentThreadId"] = parent_thread_id
        if ancestor_thread_id is not None:
            params["ancestorThreadId"] = ancestor_thread_id

        result = require_object(
            await app.request("thread/list", params),
            "thread/list result",
        )
        data = result.get("data")
        if not isinstance(data, list) or not all(
            isinstance(thread, dict)
            and isinstance(thread.get("id"), str)
            and isinstance(thread.get("status"), dict)
            for thread in data
        ):
            raise ThreadctlError("app-server returned invalid thread list data")
        if limit:
            data = data[: limit - len(threads)]
        threads.extend(data)

        next_cursor = result.get("nextCursor")
        if next_cursor is None or (limit and len(threads) >= limit):
            return threads
        if not isinstance(next_cursor, str) or next_cursor in seen_cursors:
            raise ThreadctlError("app-server returned an invalid thread-list cursor")
        seen_cursors.add(next_cursor)
        cursor = next_cursor

    return threads


async def search_threads(
    app: AppServer,
    search_term: str,
    *,
    limit: int = 20,
    sort_key: str = "recency_at",
) -> list[dict[str, Any]]:
    if not search_term.strip():
        raise ThreadctlError("thread search term must not be empty")
    if limit < 0:
        raise ThreadctlError("thread search limit must be zero or greater")

    matches: list[dict[str, Any]] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    while limit == 0 or len(matches) < limit:
        remaining = limit - len(matches) if limit else 100
        params: dict[str, Any] = {
            "searchTerm": search_term,
            "limit": min(remaining, 100),
            "sortKey": sort_key,
            "sortDirection": "desc",
            "sourceKinds": [],
        }
        if cursor is not None:
            params["cursor"] = cursor

        result = require_object(
            await app.request("thread/search", params),
            "thread/search result",
        )
        data = result.get("data")
        if not isinstance(data, list) or not all(
            isinstance(match, dict)
            and isinstance(match.get("snippet"), str)
            and isinstance(match.get("thread"), dict)
            and isinstance(match["thread"].get("id"), str)
            and isinstance(match["thread"].get("status"), dict)
            for match in data
        ):
            raise ThreadctlError("app-server returned invalid thread search data")
        if limit:
            data = data[: limit - len(matches)]
        matches.extend(data)

        next_cursor = result.get("nextCursor")
        if next_cursor is None or (limit and len(matches) >= limit):
            return matches
        if not isinstance(next_cursor, str) or next_cursor in seen_cursors:
            raise ThreadctlError("app-server returned an invalid thread-search cursor")
        seen_cursors.add(next_cursor)
        cursor = next_cursor

    return matches


async def read_thread(app: AppServer, thread_id: str) -> dict[str, Any]:
    result = require_object(
        await app.request(
            "thread/read",
            {"threadId": thread_id, "includeTurns": False},
        ),
        "thread/read result",
    )
    return require_object(result.get("thread"), "thread/read thread")


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
    result = require_object(
        await app.request("thread/turns/list", params),
        "thread/turns/list result",
    )
    data = result.get("data")
    if not isinstance(data, list) or not all(
        isinstance(turn, dict) and isinstance(turn.get("id"), str)
        for turn in data
    ):
        raise ThreadctlError("app-server returned invalid turn data")
    return result


async def list_item_page(
    app: AppServer,
    thread_id: str,
    *,
    turn_id: str | None = None,
    cursor: str | None = None,
    limit: int = 100,
    sort_direction: str = "asc",
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "threadId": thread_id,
        "limit": limit,
        "sortDirection": sort_direction,
    }
    if turn_id is not None:
        params["turnId"] = turn_id
    if cursor is not None:
        params["cursor"] = cursor
    result = require_object(
        await app.request("thread/items/list", params),
        "thread/items/list result",
    )
    data = result.get("data")
    if not isinstance(data, list) or not all(
        isinstance(entry, dict)
        and (
            (
                isinstance(entry.get("id"), str)
                and isinstance(entry.get("type"), str)
            )
            or (
                isinstance(entry.get("turnId"), str)
                and isinstance(entry.get("item"), dict)
                and isinstance(entry["item"].get("id"), str)
                and isinstance(entry["item"].get("type"), str)
            )
        )
        for entry in data
    ):
        raise ThreadctlError("app-server returned invalid item data")
    return result


async def list_thread_turns(
    app: AppServer,
    thread_id: str,
    *,
    limit: int = 1,
    items_view: str = "notLoaded",
) -> list[dict[str, Any]]:
    page = await list_turn_page(
        app,
        thread_id,
        limit=limit,
        items_view=items_view,
    )
    return page["data"]


async def get_goal(app: AppServer, thread_id: str) -> dict[str, Any] | None:
    result = require_object(
        await app.request("thread/goal/get", {"threadId": thread_id}),
        "thread/goal/get result",
    )
    goal = result.get("goal")
    if goal is not None and not isinstance(goal, dict):
        raise ThreadctlError("app-server returned invalid goal data")
    return goal


def status_name(thread_or_status: dict[str, Any]) -> str:
    status = thread_or_status.get("status", thread_or_status)
    if not isinstance(status, dict):
        return "unknown"
    return str(status.get("type", "unknown"))


async def get_thread_status(app: AppServer, thread_id: str) -> dict[str, Any]:
    thread = await read_thread(app, thread_id)
    status = thread.get("status")
    if not isinstance(status, dict):
        raise ThreadctlError("app-server returned invalid thread status")
    return status


async def require_loaded(app: AppServer, thread_id: str) -> None:
    if thread_id not in await list_loaded(app):
        raise ThreadNotLoaded(f"thread is not loaded on this app-server: {thread_id}")


async def list_background_terminals(
    app: AppServer,
    thread_id: str,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    if limit < 0:
        raise ThreadctlError("terminal list limit must be zero or greater")
    await require_loaded(app, thread_id)

    terminals: list[dict[str, Any]] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    while limit == 0 or len(terminals) < limit:
        remaining = limit - len(terminals) if limit else 100
        params: dict[str, Any] = {
            "threadId": thread_id,
            "limit": min(remaining, 100),
        }
        if cursor is not None:
            params["cursor"] = cursor

        result = require_object(
            await app.request("thread/backgroundTerminals/list", params),
            "thread/backgroundTerminals/list result",
        )
        data = result.get("data")
        if not isinstance(data, list) or not all(
            isinstance(terminal, dict)
            and isinstance(terminal.get("processId"), str)
            and isinstance(terminal.get("itemId"), str)
            and isinstance(terminal.get("command"), str)
            and isinstance(terminal.get("cwd"), str)
            for terminal in data
        ):
            raise ThreadctlError("app-server returned invalid background-terminal data")
        if limit:
            data = data[: limit - len(terminals)]
        terminals.extend(data)

        next_cursor = result.get("nextCursor")
        if next_cursor is None or (limit and len(terminals) >= limit):
            return terminals
        if not isinstance(next_cursor, str) or next_cursor in seen_cursors:
            raise ThreadctlError("app-server returned an invalid terminal-list cursor")
        seen_cursors.add(next_cursor)
        cursor = next_cursor

    return terminals


async def terminate_background_terminal(
    app: AppServer,
    thread_id: str,
    process_id: str,
    item_id: str,
) -> bool:
    terminals = await list_background_terminals(app, thread_id, limit=0)
    terminal = next(
        (terminal for terminal in terminals if terminal["processId"] == process_id),
        None,
    )
    if terminal is None:
        raise ThreadStateError(f"background terminal not found: {process_id}")
    actual_item_id = terminal["itemId"]
    if actual_item_id != item_id:
        raise ThreadStateError(
            f"background terminal identity changed for process {process_id}: "
            f"expected item {item_id}, found {actual_item_id}"
        )

    result = require_object(
        await app.request(
            "thread/backgroundTerminals/terminate",
            {"threadId": thread_id, "processId": process_id},
        ),
        "thread/backgroundTerminals/terminate result",
    )
    terminated = result.get("terminated")
    if not isinstance(terminated, bool):
        raise ThreadctlError(
            "app-server returned invalid background-terminal termination data"
        )
    return terminated


async def current_active_turn(app: AppServer, thread_id: str) -> dict[str, Any]:
    turns = await list_thread_turns(app, thread_id, limit=1)
    turn = turns[0] if turns else None
    if not isinstance(turn, dict) or turn.get("status") != "inProgress" or not turn.get("id"):
        raise ThreadStateError("active turn id is unavailable; inspect the thread and retry")
    return turn


def turn_notification(
    app: AppServer,
    method: str,
    thread_id: str,
    turn_id: str,
) -> dict[str, Any] | None:
    for notification in reversed(getattr(app, "turn_notifications", [])):
        if notification.get("method") != method:
            continue
        params = notification.get("params")
        if not isinstance(params, dict) or params.get("threadId") != thread_id:
            continue
        if method == "turn/started":
            turn = params.get("turn")
            if isinstance(turn, dict) and turn.get("id") == turn_id:
                return params
        elif params.get("turnId") == turn_id:
            return params
    return None


def client_input_notification(
    app: AppServer,
    thread_id: str,
    client_message_id: str,
) -> dict[str, Any] | None:
    for notification in reversed(getattr(app, "turn_notifications", [])):
        if notification.get("method") not in {"item/started", "item/completed"}:
            continue
        params = notification.get("params")
        if not isinstance(params, dict) or params.get("threadId") != thread_id:
            continue
        item = params.get("item")
        if (
            isinstance(item, dict)
            and item.get("type") == "userMessage"
            and item.get("clientId") == client_message_id
            and isinstance(params.get("turnId"), str)
        ):
            return params
    return None


def text_input(message: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": message, "textElements": []}]


def is_steer_state_error(error: AppServerResponseError) -> bool:
    message = str(error)
    return any(
        fragment in message
        for fragment in (
            "no active turn to steer",
            "expected active turn id",
            "cannot steer a review turn",
            "cannot steer a compact turn",
        )
    )


def is_parent_owned_input_error(error: AppServerResponseError) -> bool:
    return DIRECT_INPUT_TO_V2_SUBAGENT in str(error)


async def confirm_input(
    app: AppServer,
    thread_id: str,
    submitted_turn_id: str,
    client_message_id: str,
    timeout: float,
) -> dict[str, Any]:
    def confirmed(actual_turn_id: str, turn_status: Any = None) -> dict[str, Any]:
        return {
            "threadId": thread_id,
            "turnId": actual_turn_id,
            "submittedTurnId": submitted_turn_id,
            "clientMessageId": client_message_id,
            "delivery": (
                "started"
                if actual_turn_id == submitted_turn_id
                else "steered"
            ),
            "turnStatus": turn_status,
        }

    deadline = time.monotonic() + timeout
    native_supported = True
    turn_listing_supported = True
    while time.monotonic() < deadline:
        notification = client_input_notification(
            app,
            thread_id,
            client_message_id,
        )
        if notification is not None:
            return confirmed(str(notification["turnId"]))

        if native_supported:
            try:
                page = await list_item_page(
                    app,
                    thread_id,
                    limit=100,
                    sort_direction="desc",
                )
                for entry in page["data"]:
                    wrapped = entry.get("item")
                    item = wrapped if isinstance(wrapped, dict) else entry
                    if (
                        item.get("type") == "userMessage"
                        and item.get("clientId") == client_message_id
                    ):
                        actual_turn_id = entry.get("turnId")
                        if isinstance(actual_turn_id, str):
                            return confirmed(actual_turn_id)
            except AppServerResponseError as exc:
                if not unsupported_method(exc):
                    raise
                native_supported = False

        if turn_listing_supported:
            try:
                page = await list_turn_page(
                    app,
                    thread_id,
                    limit=5,
                    items_view="full",
                )
            except AppServerResponseError as exc:
                if not unsupported_method(exc):
                    raise
                turn_listing_supported = False
            else:
                for turn in page["data"]:
                    for item in turn.get("items", []):
                        if not isinstance(item, dict):
                            continue
                        if (
                            item.get("type") == "userMessage"
                            and item.get("clientId") == client_message_id
                        ):
                            return confirmed(
                                str(turn.get("id") or submitted_turn_id),
                                turn.get("status"),
                            )
        if time.monotonic() < deadline:
            await asyncio.sleep(0.1)
    raise DeliveryUncertain(submitted_turn_id, client_message_id)


async def start_turn(
    app: AppServer,
    thread_id: str,
    message: str,
    *,
    confirmation_timeout: float | None = None,
) -> dict[str, Any]:
    await require_loaded(app, thread_id)
    status = await get_thread_status(app, thread_id)
    name = status_name(status)
    if name != "idle":
        raise ThreadStateError(f"thread is {name}; refusing to start a new turn")

    client_message_id = uuid.uuid4().hex
    try:
        result = require_object(
            await app.request(
                "turn/start",
                {
                    "threadId": thread_id,
                    "clientUserMessageId": client_message_id,
                    "input": text_input(message),
                },
            ),
            "turn/start result",
        )
        turn = require_object(result.get("turn"), "turn/start turn")
        turn_id = turn.get("id")
        if not isinstance(turn_id, str) or not turn_id:
            raise ThreadctlError("app-server returned turn/start without a turn id")
    except AppServerResponseError as exc:
        if is_parent_owned_input_error(exc):
            raise DirectInputUnsupported(PARENT_OWNED_INPUT_ERROR) from exc
        raise
    except (OSError, ThreadctlError, websockets.WebSocketException) as exc:
        raise DeliveryUncertain(None, client_message_id) from exc
    try:
        return await confirm_input(
            app,
            thread_id,
            turn_id,
            client_message_id,
            confirmation_timeout if confirmation_timeout is not None else app.timeout,
        )
    except DeliveryUncertain:
        raise
    except (OSError, ThreadctlError, websockets.WebSocketException) as exc:
        raise DeliveryUncertain(turn_id, client_message_id) from exc


async def notify_thread(
    app: AppServer,
    thread_id: str,
    author: str,
    message: str,
) -> dict[str, Any]:
    await require_loaded(app, thread_id)
    item = {
        "type": "agent_message",
        "id": None,
        "author": author,
        "recipient": thread_id,
        "content": [{"type": "input_text", "text": message}],
    }
    try:
        require_object(
            await app.request(
                "thread/inject_items",
                {"threadId": thread_id, "items": [item]},
            ),
            "thread/inject_items result",
        )
    except AppServerResponseError:
        raise
    except (OSError, ThreadctlError, websockets.WebSocketException) as exc:
        raise ThreadctlError(
            "notification outcome is uncertain; inspect the target before retrying"
        ) from exc
    return {
        "threadId": thread_id,
        "author": author,
        "outcome": "accepted",
    }


def wake_result(
    thread_id: str,
    outcome: str,
    *,
    turn_id: str | None = None,
    observed_status: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "threadId": thread_id,
        "outcome": outcome,
    }
    if turn_id is not None:
        result["turnId"] = turn_id
    if observed_status is not None:
        result["observedStatus"] = observed_status
    if reason is not None:
        result["reason"] = reason
    return result


async def confirm_wake(
    app: AppServer,
    thread_id: str,
    turn_id: str,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    observed_status: str | None = None
    observed_turn_id: str | None = None

    while time.monotonic() < deadline:
        started = turn_notification(app, "turn/started", thread_id, turn_id)
        if started is not None:
            turn = started["turn"]
            return wake_result(
                thread_id,
                "confirmedStarted",
                turn_id=turn_id,
                observed_status=str(turn.get("status") or "unknown"),
            )

        error = turn_notification(app, "error", thread_id, turn_id)
        if error is not None and not error.get("willRetry"):
            return wake_result(
                thread_id,
                "rejected",
                turn_id=turn_id,
                reason=str(error.get("error") or "turn start failed"),
            )

        try:
            page = await list_turn_page(
                app,
                thread_id,
                limit=5,
                items_view="notLoaded",
            )
        except (OSError, ThreadctlError, websockets.WebSocketException) as exc:
            return wake_result(
                thread_id,
                "uncertain",
                turn_id=turn_id,
                observed_status=observed_status,
                reason=str(exc),
            )

        for turn in page["data"]:
            candidate_id = str(turn.get("id") or "")
            candidate_status = str(turn.get("status") or "unknown")
            if candidate_id == turn_id:
                return wake_result(
                    thread_id,
                    "confirmedStarted",
                    turn_id=turn_id,
                    observed_status=candidate_status,
                )
            if candidate_status == "inProgress" and observed_turn_id is None:
                observed_turn_id = candidate_id or None
                observed_status = "active"

        if time.monotonic() < deadline:
            await asyncio.sleep(0.1)

    return wake_result(
        thread_id,
        "uncertain",
        turn_id=turn_id,
        observed_status=observed_status,
        reason=(
            f"turn {turn_id} was not observed within {timeout:g}s"
            + (
                f"; another active turn was {observed_turn_id}"
                if observed_turn_id is not None
                else ""
            )
        ),
    )


async def wake_thread(
    app: AppServer,
    thread_id: str,
    *,
    confirmation_timeout: float | None = None,
) -> dict[str, Any]:
    if thread_id not in await list_loaded(app):
        return wake_result(thread_id, "notLoaded")

    status = await get_thread_status(app, thread_id)
    name = status_name(status)
    if name == "active":
        turn_id = None
        try:
            turn_id = str((await current_active_turn(app, thread_id))["id"])
        except (OSError, ThreadctlError, websockets.WebSocketException):
            pass
        return wake_result(
            thread_id,
            "notSubmittedActive",
            turn_id=turn_id,
            observed_status=name,
        )
    if name == "notLoaded":
        return wake_result(thread_id, "notLoaded", observed_status=name)
    if name != "idle":
        return wake_result(
            thread_id,
            "rejected",
            observed_status=name,
            reason=f"thread status is {name}",
        )

    try:
        result = require_object(
            await app.request(
                "turn/start",
                {"threadId": thread_id, "input": []},
            ),
            "turn/start result",
        )
        turn = require_object(result.get("turn"), "turn/start turn")
        turn_id = turn.get("id")
        if not isinstance(turn_id, str) or not turn_id:
            raise ThreadctlError("app-server returned turn/start without a turn id")
    except AppServerResponseError as exc:
        reason = (
            PARENT_OWNED_INPUT_ERROR
            if is_parent_owned_input_error(exc)
            else str(exc)
        )
        return wake_result(thread_id, "rejected", reason=reason)
    except (OSError, ThreadctlError, websockets.WebSocketException) as exc:
        return wake_result(thread_id, "uncertain", reason=str(exc))

    return await confirm_wake(
        app,
        thread_id,
        turn_id,
        confirmation_timeout if confirmation_timeout is not None else app.timeout,
    )


async def steer_turn(
    app: AppServer,
    thread_id: str,
    turn_id: str,
    message: str,
) -> dict[str, Any]:
    await require_loaded(app, thread_id)
    client_message_id = uuid.uuid4().hex
    try:
        result = require_object(
            await app.request(
                "turn/steer",
                {
                    "threadId": thread_id,
                    "expectedTurnId": turn_id,
                    "clientUserMessageId": client_message_id,
                    "input": text_input(message),
                },
            ),
            "turn/steer result",
        )
        accepted_turn_id = result.get("turnId")
        if accepted_turn_id != turn_id:
            raise ThreadctlError("app-server returned an unexpected steered turn id")
    except AppServerResponseError as exc:
        if is_parent_owned_input_error(exc):
            raise DirectInputUnsupported(PARENT_OWNED_INPUT_ERROR) from exc
        if is_steer_state_error(exc):
            raise ThreadStateError(str(exc)) from exc
        raise
    except (OSError, ThreadctlError, websockets.WebSocketException) as exc:
        raise DeliveryUncertain(turn_id, client_message_id) from exc
    return {
        "threadId": thread_id,
        "turnId": turn_id,
        "clientMessageId": client_message_id,
        "delivery": "steered",
    }


async def deliver_input(
    app: AppServer,
    thread_id: str,
    message: str,
    *,
    allow_active: bool,
) -> dict[str, Any]:
    await require_loaded(app, thread_id)
    status = await get_thread_status(app, thread_id)
    name = status_name(status)
    if name == "idle":
        return await start_turn(app, thread_id, message)
    if name == "active" and allow_active:
        turn = await current_active_turn(app, thread_id)
        return await steer_turn(app, thread_id, str(turn["id"]), message)
    if name == "active":
        raise ThreadStateError("thread is active; active steering was not allowed")
    if name == "notLoaded":
        raise ThreadNotLoaded(f"thread is not loaded on this app-server: {thread_id}")
    raise ThreadStateError(f"thread status is {name}; refusing to deliver input")


async def read_turn(app: AppServer, thread_id: str, turn_id: str) -> dict[str, Any]:
    cursor: str | None = None
    seen_cursors: set[str] = set()
    while True:
        page = await list_turn_page(
            app,
            thread_id,
            cursor=cursor,
            limit=50,
            items_view="summary",
        )
        for turn in page["data"]:
            if isinstance(turn, dict) and turn.get("id") == turn_id:
                return turn
        next_cursor = page.get("nextCursor")
        if next_cursor is None:
            raise ThreadctlError(f"turn not found: {turn_id}")
        if not isinstance(next_cursor, str) or next_cursor in seen_cursors:
            raise ThreadctlError("app-server returned an invalid turn cursor")
        seen_cursors.add(next_cursor)
        cursor = next_cursor


async def wait_for_turn_terminal(
    app: AppServer,
    thread_id: str,
    turn_id: str,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        turn = await read_turn(app, thread_id, turn_id)
        if turn.get("status") != "inProgress":
            return turn
        await asyncio.sleep(0.1)
    raise ThreadctlError(f"timed out waiting for turn to stop: {turn_id}")


async def interrupt_thread(
    app: AppServer,
    thread_id: str,
    turn_id: str,
    *,
    wait: bool,
) -> dict[str, Any]:
    await require_loaded(app, thread_id)
    await app.request(
        "turn/interrupt",
        {"threadId": thread_id, "turnId": turn_id},
    )
    result: dict[str, Any] = {
        "threadId": thread_id,
        "turnId": turn_id,
        "status": "requested",
    }
    if wait:
        turn = await wait_for_turn_terminal(app, thread_id, turn_id, app.timeout)
        result["status"] = str(turn.get("status") or "unknown")
    return result


async def resume_thread(
    app: AppServer,
    thread_id: str,
    *,
    continue_goal: bool = False,
) -> dict[str, Any]:
    if not continue_goal:
        raise ThreadStateError(
            "resume can continue an active goal without input; "
            "pass --continue-goal to acknowledge this"
        )

    result = require_object(
        await app.request(
            "thread/resume",
            {"threadId": thread_id, "excludeTurns": True},
        ),
        "thread/resume result",
    )
    return require_object(result.get("thread"), "thread/resume thread")
