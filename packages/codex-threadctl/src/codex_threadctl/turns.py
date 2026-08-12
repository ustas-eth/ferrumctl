from __future__ import annotations

import time
from typing import Any

from .appserver import AppServer
from .errors import ThreadctlError
from .history import MaterializedSelection, select_materialized_items, summary_items
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
    summary = dict(turn)
    summary["items"] = summary_items(turn.get("items", []))
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
    history_backend: str = "thread/turns/list",
    history_error: str | None = None,
    recent_items: list[dict[str, Any]] | None = None,
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
        "agentPath",
        "agentDepth",
        "canAcceptDirectInput",
        "inputOwner",
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
        "historyBackend": history_backend,
        "historyError": history_error,
        "recentItems": [
            summarize_item(item) for item in (recent_items or [])
        ],
        "latestTurn": summarize_turn(latest, item_limit) if latest else None,
        "previousTurn": summarize_turn(previous, 0) if previous else None,
    }


async def recent_messages(
    app: AppServer,
    thread_id: str,
    *,
    turn_id: str | None = None,
    after: tuple[str, str] | None = None,
    before: tuple[str, str] | None = None,
    limit: int,
) -> tuple[list[dict[str, Any]], str]:
    selection = await select_materialized_items(
        app,
        thread_id,
        turn_id=turn_id,
        after=after,
        before=before,
        types={"userMessage", "agentMessage"},
        limit=limit,
    )
    return (
        [message_record(entry.turn, entry.item) for entry in selection.entries],
        selection.backend,
    )


async def find_message(
    app: AppServer,
    thread_id: str,
    turn_id: str,
    item_id: str,
) -> dict[str, Any]:
    selection: MaterializedSelection = await select_materialized_items(
        app,
        thread_id,
        turn_id=turn_id,
        limit=0,
    )
    item = next(
        (entry for entry in selection.entries if entry.item["id"] == item_id),
        None,
    )
    if item is None:
        raise ThreadctlError(f"message item not found in turn {turn_id}: {item_id}")
    if item.item["type"] not in {"userMessage", "agentMessage"}:
        raise ThreadctlError(
            f"item is not a conversation message: {item.item['type']}"
        )
    return message_record(item.turn, item.item)
