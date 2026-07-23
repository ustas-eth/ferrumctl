from __future__ import annotations

import time
from typing import Any

from .appserver import AppServer
from .errors import ThreadctlError
from .history import MaterializedSelection, select_materialized_items
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
