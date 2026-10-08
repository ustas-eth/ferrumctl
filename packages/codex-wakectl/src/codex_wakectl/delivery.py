from __future__ import annotations

from typing import Any

import websockets

from codex_threadctl.appserver import (
    can_start_turn,
    current_active_turn,
    deliver_input,
    get_thread_status,
    list_loaded,
    list_thread_turns,
    notify_thread,
    wake_thread,
)
from codex_threadctl.attention import CONTROL_ERRORS, load_for_attention, wake_after_load
from codex_threadctl.errors import (
    DirectInputUnsupported,
    NotificationUncertain,
    ThreadNotLoaded,
    ThreadStateError,
    ThreadctlError,
)
from codex_threadctl.formatting import status_name
from codex_threadctl.response_items import agent_message_id

from .errors import EventDeliveryUncertain, WakectlError


def event_item_id(job: dict[str, Any]) -> str:
    sequence = int(job.get("fireCount") or 0) + 1
    return agent_message_id(f"codex-wakectl:event:{job['id']}:{sequence}")


def event_text(job: dict[str, Any], reason: str) -> str:
    condition = job["condition"]
    kind = condition["type"]
    event = f"{job['id']}/{int(job.get('fireCount') or 0) + 1}"
    if kind == "time":
        detail = "scheduled time reached"
    elif kind == "goal":
        detail = f"goal condition for {condition['threadId']} matched: {reason}"
    elif kind == "stop":
        detail = f"turn condition for {condition['threadId']} matched: {reason}"
    elif kind == "cmd":
        detail = "host condition matched"
    else:
        raise WakectlError(f"unknown condition type: {kind}")
    return f"Scheduled event {event}: {detail}."


async def _active_turn_id(app: Any, thread_id: str) -> str | None:
    try:
        return str((await current_active_turn(app, thread_id))["id"])
    except (OSError, ThreadctlError, websockets.WebSocketException):
        return None


async def deliver_event(
    app: Any,
    job: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    action = job["action"]
    thread_id = job["targetThreadId"]
    loading = None
    if action.get("resume"):
        loading = await load_for_attention(app, thread_id, action.get("resumeConfig"))
    elif thread_id not in await list_loaded(app):
        raise ThreadNotLoaded(f"thread is not loaded on this app-server: {thread_id}")
    resumed = loading is not None and loading["outcome"] == "resumed"

    status = status_name(await get_thread_status(app, thread_id))
    item_id = event_item_id(job)

    async def inject_event() -> dict[str, Any]:
        try:
            result = await notify_thread(
                app, thread_id, "wakectl", event_text(job, reason), item_id=item_id,
            )
        except NotificationUncertain as exc:
            raise EventDeliveryUncertain(item_id, reason=str(exc), loading=loading) from exc
        if loading is not None:
            result["loading"] = loading
        return result

    if status == "active":
        if not (action.get("notifyActive") or resumed):
            raise ThreadStateError(
                "thread is active; active notification was not allowed"
            )
        if not resumed:
            result = await inject_event()
            result.update({"turnId": await _active_turn_id(app, thread_id),
                           "delivery": "notifiedActive"})
            return result
    elif not can_start_turn(status):
        if status == "notLoaded":
            raise ThreadNotLoaded(
                f"thread is not loaded on this app-server: {thread_id}"
            )
        raise ThreadStateError(f"thread status is {status}; refusing to deliver event")

    # A continuation that finished before injection cannot attend to this event.
    continuation_before_event = status == "active"
    if resumed and not continuation_before_event:
        turns = await list_thread_turns(app, thread_id, limit=1)
        continuation_before_event = bool(
            turns and turns[0]["id"] != loading["previousTurnId"]
        )
    notification = await inject_event()
    try:
        wake = (await wake_after_load(app, thread_id, loading)
                if loading is not None and not continuation_before_event
                else await wake_thread(app, thread_id))
    except CONTROL_ERRORS as exc:
        raise EventDeliveryUncertain(item_id, reason=str(exc), loading=loading) from exc
    outcome = wake["outcome"]
    if outcome in {"confirmedStarted", "confirmedResumed"}:
        mode = "resumedStarted" if resumed else "eventStarted"
        if outcome == "confirmedResumed":
            mode = "resumedContinued"
        notification.update(
            {
                "turnId": wake.get("turnId"),
                "delivery": mode,
            }
        )
        return notification
    if outcome == "notSubmittedActive":
        notification.update(
            {
                "turnId": wake.get("turnId"),
                "delivery": "resumedActive" if resumed and status == "active" else "eventNotifiedActive",
            }
        )
        return notification
    reason = str(wake.get("reason") or outcome)
    if "native parent" in reason:
        raise DirectInputUnsupported(reason)
    raise EventDeliveryUncertain(
        item_id,
        turn_id=wake.get("turnId"),
        reason=reason,
        loading=loading,
    )


async def deliver_action(
    app: Any,
    job: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    action = job["action"]
    kind = action.get("type")
    if kind == "event":
        return await deliver_event(app, job, reason)
    if kind == "input":
        return await deliver_input(
            app,
            job["targetThreadId"],
            action["message"],
            allow_active=bool(action.get("allowActive")),
        )
    raise WakectlError(f"unknown action type: {kind}")
