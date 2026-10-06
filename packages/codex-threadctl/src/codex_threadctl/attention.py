"""Explicit cold loading and agent-message delivery, without retry policy."""
from __future__ import annotations

import asyncio
import time
from typing import Any

import websockets

from .appserver import (
    AppServer, get_goal, list_loaded, notify_thread, list_thread_turns, wake_thread,
)
from .configuration import resume_thread
from .errors import AppServerResponseError, OperationError, ThreadctlError, error_record

SUCCESSFUL_WAKES = {"confirmedStarted", "notSubmittedActive", "confirmedResumed"}
CONTROL_ERRORS = (OSError, ThreadctlError, websockets.WebSocketException)


async def continuation_goal(app: AppServer, thread_id: str) -> dict[str, Any] | None:
    try:
        return await get_goal(app, thread_id)
    except AppServerResponseError as exc:
        # This native response confirms continuation is disabled. Other failures
        # cannot safely be treated as absence of an active goal.
        if str(exc) == "goals feature is disabled":
            return None
        raise


async def load_for_attention(
    app: AppServer, thread_id: str, config: dict[str, Any] | None,
) -> dict[str, Any]:
    """Observe before loading: a resumed active goal can start asynchronously."""
    if thread_id in await list_loaded(app):
        return {"outcome": "alreadyLoaded", "configSubmitted": False}
    goal = await continuation_goal(app, thread_id)
    turns = await list_thread_turns(app, thread_id, limit=1)
    previous = turns[0]["id"] if turns else None
    thread = await resume_thread(
        app, thread_id, continue_goal=True, config_overrides=config,
    )
    return {
        "outcome": "resumed", "configSubmitted": config is not None,
        "settings": thread.get("settings", {}),
        "previousTurnId": previous,
        "goalWasActive": goal is not None and goal.get("status") == "active",
        **({"configRequest": thread["configRequest"]} if "configRequest" in thread else {}),
    }


async def wake_after_load(
    app: AppServer, thread_id: str, loading: dict[str, Any],
) -> dict[str, Any]:
    if loading["outcome"] != "resumed":
        return await wake_thread(app, thread_id)
    # Check both sides of resume; a concurrent goal write can change its status.
    goal = await continuation_goal(app, thread_id)
    if not loading["goalWasActive"] and not (goal and goal.get("status") == "active"):
        return await wake_thread(app, thread_id)
    deadline = time.monotonic() + app.timeout
    while True:
        turns = await list_thread_turns(app, thread_id, limit=1)
        if turns and turns[0]["id"] != loading["previousTurnId"]:
            return {
                "threadId": thread_id, "outcome": "confirmedResumed",
                "turnId": turns[0]["id"], "observedStatus": turns[0].get("status"),
            }
        if time.monotonic() >= deadline:
            return {
                "threadId": thread_id, "outcome": "continuationUnconfirmed",
                "reason": "loaded with an active goal but no new turn was observed; "
                          "inspect before requesting another wake",
            }
        await asyncio.sleep(0.1)


async def wake_with_resume(
    app: AppServer, thread_id: str, config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    loading = await load_for_attention(app, thread_id, config)
    try:
        result = await wake_after_load(app, thread_id, loading)
    except CONTROL_ERRORS as exc:
        raise OperationError(
            "wake could not be confirmed after loading; inspect before retrying",
            code="wakeAfterLoadFailed", outcome="partial", threadId=thread_id,
            loading=loading, cause=error_record(exc),
        ) from exc
    return {**result, "loading": loading}


async def send_message(
    app: AppServer, thread_id: str, author: str, message: str, *,
    wake: bool = False, resume: bool = False, config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if resume and not wake:
        raise ThreadctlError("send --resume requires --wake; loading may continue a goal")
    if config is not None and not resume:
        raise ThreadctlError("--config-file requires --resume")
    loading = await load_for_attention(app, thread_id, config) if resume else None
    continuation_before_message = False
    try:
        if loading and loading["outcome"] == "resumed":
            turns = await list_thread_turns(app, thread_id, limit=1)
            continuation_before_message = bool(
                turns and turns[0]["id"] != loading["previousTurnId"]
            )
        accepted = await notify_thread(app, thread_id, author, message)
    except CONTROL_ERRORS as exc:
        if loading and loading["outcome"] == "resumed":
            raise OperationError(
                "thread loaded but agent-message acceptance was not confirmed",
                code="sendAfterLoadFailed", outcome="partial", threadId=thread_id,
                loading=loading, messageDelivery=error_record(exc),
            ) from exc
        raise
    result = {**accepted, "messageRole": "agent", "messageOutcome": "accepted"}
    if loading is not None:
        result["loading"] = loading
    if wake:
        try:
            # A continuation already observed before this message cannot stand
            # in for its wake: it might have finished before injection. Use the
            # normal post-send status check then; wait only for a still-pending
            # cold goal continuation.
            attention = (await wake_after_load(app, thread_id, loading)
                         if loading is not None and not continuation_before_message
                         else await wake_thread(app, thread_id))
        except CONTROL_ERRORS as exc:
            attention = error_record(exc)
        result["wake"] = attention
        if attention["outcome"] not in SUCCESSFUL_WAKES:
            result["outcome"] = "partial"
    return result
