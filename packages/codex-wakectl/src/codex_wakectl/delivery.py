from __future__ import annotations

from typing import Any

import websockets

from codex_threadctl.appserver import (
    current_active_turn,
    deliver_input,
    get_thread_status,
    list_loaded,
    notify_thread,
    resume_thread,
    wake_thread,
)
from codex_threadctl.errors import (
    DirectInputUnsupported,
    ThreadNotLoaded,
    ThreadStateError,
    ThreadctlError,
)
from codex_threadctl.formatting import status_name

from .errors import EventDeliveryUncertain, WakectlError


def event_item_id(job: dict[str, Any]) -> str:
    sequence = int(job.get("fireCount") or 0) + 1
    return f"amsg_wake_{job['id']}_{sequence}"


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
    resumed = False
    if thread_id not in await list_loaded(app):
        if not action.get("resume"):
            raise ThreadNotLoaded(
                f"thread is not loaded on this app-server: {thread_id}"
            )
        await resume_thread(app, thread_id, continue_goal=True)
        resumed = True

    status = status_name(await get_thread_status(app, thread_id))
    item_id = event_item_id(job)
    if status == "active":
        if not (action.get("notifyActive") or resumed):
            raise ThreadStateError(
                "thread is active; active notification was not allowed"
            )
        result = await notify_thread(
            app,
            thread_id,
            "wakectl",
            event_text(job, reason),
            item_id=item_id,
        )
        result.update(
            {
                "turnId": await _active_turn_id(app, thread_id),
                "delivery": "resumedActive" if resumed else "notifiedActive",
            }
        )
        return result
    if status != "idle":
        if status == "notLoaded":
            raise ThreadNotLoaded(
                f"thread is not loaded on this app-server: {thread_id}"
            )
        raise ThreadStateError(f"thread status is {status}; refusing to deliver event")

    notification = await notify_thread(
        app,
        thread_id,
        "wakectl",
        event_text(job, reason),
        item_id=item_id,
    )
    wake = await wake_thread(app, thread_id)
    outcome = wake["outcome"]
    if outcome == "confirmedStarted":
        notification.update(
            {
                "turnId": wake.get("turnId"),
                "delivery": "resumedStarted" if resumed else "eventStarted",
            }
        )
        return notification
    if outcome == "notSubmittedActive":
        notification.update(
            {
                "turnId": wake.get("turnId"),
                "delivery": "eventNotifiedActive",
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
