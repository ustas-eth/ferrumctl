from __future__ import annotations

import time
from typing import Any

from .appserver import AppServer, list_turn_page
from .errors import ThreadctlError
from .items import message_record, summarize_item


def summarize_turn(turn: dict[str, Any], item_limit: int) -> dict[str, Any]:
    items = turn.get("items", [])
    if item_limit > 0:
        items = items[-item_limit:]
    started_at = turn.get("startedAt")
    completed_at = turn.get("completedAt")
    now = int(time.time())
    return {
        "id": turn.get("id"),
        "status": turn.get("status"),
        "itemsView": turn.get("itemsView"),
        "error": turn.get("error"),
        "startedAt": started_at,
        "completedAt": completed_at,
        "durationMs": turn.get("durationMs"),
        "startedAgoSeconds": max(0, now - started_at) if started_at is not None else None,
        "completedAgoSeconds": (
            max(0, now - completed_at) if completed_at is not None else None
        ),
        "items": [summarize_item(item) for item in items],
    }


def summary_view(turn: dict[str, Any]) -> dict[str, Any]:
    items = turn.get("items", [])
    first_user = next(
        (item for item in items if item.get("type") == "userMessage"),
        None,
    )
    final_agent = next(
        (item for item in reversed(items) if item.get("type") == "agentMessage"),
        None,
    )
    if (
        first_user is not None
        and final_agent is not None
        and first_user.get("id") != final_agent.get("id")
    ):
        summary_items = [first_user, final_agent]
    elif first_user is not None:
        summary_items = [first_user]
    elif final_agent is not None:
        summary_items = [final_agent]
    else:
        summary_items = []

    summary = dict(turn)
    summary["items"] = summary_items
    summary["itemsView"] = "summary"
    return summary


def build_inspection(
    thread: dict[str, Any],
    *,
    loaded: bool,
    goal: dict[str, Any] | None,
    goal_error: str | None,
    turns: list[dict[str, Any]],
    item_limit: int,
    context: dict[str, Any] | None,
    compaction: dict[str, Any] | None,
    context_error: str | None = None,
) -> dict[str, Any]:
    latest = turns[0] if turns else None
    previous = next(
        (
            turn
            for turn in turns[1:]
            if latest is None or turn.get("id") != latest.get("id")
        ),
        None,
    )
    if previous is not None:
        previous = summary_view(previous)
    metadata_keys = (
        "id",
        "status",
        "cwd",
        "name",
        "agentNickname",
        "agentRole",
        "parentThreadId",
        "forkedFromId",
        "source",
        "cliVersion",
        "createdAt",
        "updatedAt",
        "recencyAt",
    )
    thread_summary = {key: thread.get(key) for key in metadata_keys}
    thread_summary["loaded"] = loaded
    return {
        "thread": thread_summary,
        "context": context,
        "contextError": context_error,
        "compaction": compaction,
        "goal": goal,
        "goalError": goal_error,
        "latestTurn": summarize_turn(latest, item_limit) if latest else None,
        "previousTurn": summarize_turn(previous, 0) if previous else None,
    }


async def recent_messages(
    app: AppServer,
    thread_id: str,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    cursor: str | None = None
    seen_cursors: set[str] = set()
    newest_first_batches: list[list[dict[str, Any]]] = []
    count = 0

    while limit == 0 or count < limit:
        page = await list_turn_page(
            app,
            thread_id,
            cursor=cursor,
            limit=10,
            sort_direction="desc",
            items_view="full",
        )
        turns = page.get("data", [])
        for turn in turns:
            messages = [
                message_record(turn, item)
                for item in turn.get("items", [])
                if item.get("type") in {"userMessage", "agentMessage"}
            ]
            newest_first_batches.append(messages)
            count += len(messages)

        next_cursor = page.get("nextCursor")
        if not turns or next_cursor is None:
            break
        if not isinstance(next_cursor, str) or next_cursor in seen_cursors:
            raise ThreadctlError("app-server repeated a turn pagination cursor")
        seen_cursors.add(next_cursor)
        cursor = next_cursor

    chronological = [
        message
        for batch in reversed(newest_first_batches)
        for message in batch
    ]
    return chronological if limit == 0 else chronological[-limit:]


async def find_message(
    app: AppServer,
    thread_id: str,
    turn_id: str,
    item_id: str,
) -> dict[str, Any]:
    cursor: str | None = None
    seen_cursors: set[str] = set()
    while True:
        page = await list_turn_page(
            app,
            thread_id,
            cursor=cursor,
            limit=10,
            sort_direction="desc",
            items_view="full",
        )
        turns = page.get("data", [])
        for turn in turns:
            if turn.get("id") != turn_id:
                continue
            item = next(
                (entry for entry in turn.get("items", []) if entry.get("id") == item_id),
                None,
            )
            if item is None:
                raise ThreadctlError(f"message item not found in turn {turn_id}: {item_id}")
            if item.get("type") not in {"userMessage", "agentMessage"}:
                raise ThreadctlError(f"item is not a conversation message: {item.get('type')}")
            return message_record(turn, item)

        next_cursor = page.get("nextCursor")
        if not turns or next_cursor is None:
            raise ThreadctlError(f"turn not found: {turn_id}")
        if not isinstance(next_cursor, str) or next_cursor in seen_cursors:
            raise ThreadctlError("app-server repeated a turn pagination cursor")
        seen_cursors.add(next_cursor)
        cursor = next_cursor
