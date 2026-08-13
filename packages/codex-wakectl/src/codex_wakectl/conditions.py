from __future__ import annotations

import argparse
import os
import subprocess
import uuid
from typing import Any

from codex_threadctl.appserver import get_goal, list_turn_page, list_thread_turns

from .constants import DEFAULT_TIMEOUT, TERMINAL_TURN_STATUSES
from .errors import WakectlError
from .parsing import format_time, now_seconds


def time_condition_ready(condition: dict[str, Any]) -> tuple[bool, dict[str, Any], str]:
    ready = now_seconds() >= condition["at"]
    return ready, {}, "ready" if ready else f"waiting until {format_time(condition['at'])}"


def cmd_condition_ready(
    condition: dict[str, Any],
    timeout: float,
) -> tuple[bool, dict[str, Any], str]:
    try:
        proc = subprocess.run(
            condition["argv"],
            cwd=condition.get("cwd") or None,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, {}, f"command timed out after {timeout:g}s"
    if proc.returncode == 0:
        return True, {}, "command exited 0"
    return False, {}, f"command exited {proc.returncode}"


async def goal_condition_ready(
    app: Any,
    condition: dict[str, Any],
    job: dict[str, Any] | None = None,
) -> tuple[bool, dict[str, Any], str]:
    goal = await get_goal(app, condition["threadId"])
    if goal is None:
        return False, {}, "no goal"

    tokens_used = int(goal.get("tokensUsed") or 0)
    time_used = int(goal.get("timeUsedSeconds") or 0)
    created_at = goal.get("createdAt")
    previous_created_at = condition.get("goalCreatedAt")
    identity_updates: dict[str, Any] = {}
    if previous_created_at is None and created_at is not None:
        updated_condition = dict(condition)
        updated_condition["goalCreatedAt"] = created_at
        condition = updated_condition
        identity_updates["condition"] = updated_condition
    elif created_at is not None and created_at != previous_created_at:
        if job is None:
            raise WakectlError("watched goal was replaced")
        return False, {"status": "superseded"}, "watched goal was replaced"

    def combined(updates: dict[str, Any] | None = None) -> dict[str, Any]:
        return {**identity_updates, **(updates or {})}

    reset_updates: dict[str, Any] = {}
    if "tokensUsedEvery" in condition:
        interval = condition["tokensUsedEvery"]
        bucket = tokens_used // interval
        previous = int((job or {}).get("lastTokensUsedBucket") or 0)
        if bucket < previous:
            reset_updates["lastTokensUsedBucket"] = bucket
    if "timeUsedEvery" in condition:
        interval = condition["timeUsedEvery"]
        bucket = time_used // interval
        previous = int((job or {}).get("lastTimeUsedBucket") or 0)
        if bucket < previous:
            reset_updates["lastTimeUsedBucket"] = bucket
    if reset_updates:
        return False, combined(reset_updates), "goal usage counters reset"

    statuses = condition.get("statuses")
    if statuses and goal.get("status") not in statuses:
        return False, combined(), f"status is {goal.get('status')}"

    token_budget = goal.get("tokenBudget")
    matched: list[str] = []

    if statuses:
        matched.append(f"status is {goal.get('status')}")

    if "tokensLeftLte" in condition:
        if token_budget is None:
            return False, combined(), "goal has no token budget"
        tokens_left = int(token_budget) - tokens_used
        if tokens_left > condition["tokensLeftLte"]:
            return False, combined(), f"tokens left {tokens_left}"
        matched.append(f"tokens left {tokens_left}")

    if "tokensUsedGte" in condition and tokens_used < condition["tokensUsedGte"]:
        return False, combined(), f"tokens used {tokens_used}"
    if "tokensUsedGte" in condition:
        matched.append(f"tokens used {tokens_used}")

    if "timeUsedGte" in condition and time_used < condition["timeUsedGte"]:
        return False, combined(), f"time used {time_used}s"
    if "timeUsedGte" in condition:
        matched.append(f"time used {time_used}s")

    if "tokensUsedEvery" in condition:
        interval = condition["tokensUsedEvery"]
        bucket = tokens_used // interval
        previous = int((job or {}).get("lastTokensUsedBucket") or 0)
        if bucket <= 0 or bucket <= previous:
            return False, combined(), f"tokens used bucket {bucket}"
        return (
            True,
            combined({"lastTokensUsedBucket": bucket}),
            f"tokens used {tokens_used}",
        )

    if "timeUsedEvery" in condition:
        interval = condition["timeUsedEvery"]
        bucket = time_used // interval
        previous = int((job or {}).get("lastTimeUsedBucket") or 0)
        if bucket <= 0 or bucket <= previous:
            return False, combined(), f"time used bucket {bucket}"
        return (
            True,
            combined({"lastTimeUsedBucket": bucket}),
            f"time used {time_used}s",
        )

    return True, combined(), "; ".join(matched) or "goal predicate matched"


def with_turn_cursor(
    condition: dict[str, Any],
    turn: dict[str, Any] | None,
) -> dict[str, Any]:
    updated = dict(condition)
    updated.pop("observedActive", None)
    updated.pop("lastStatus", None)
    updated["cursorTurnId"] = turn.get("id") if turn else None
    updated["cursorTurnStatus"] = turn.get("status") if turn else None
    return updated


async def seed_stop_condition(app: Any, condition: dict[str, Any]) -> dict[str, Any]:
    exact_turn_id = condition.get("turnId")
    if exact_turn_id is not None:
        if exact_turn_id == "latest":
            turns = await list_thread_turns(
                app,
                condition["threadId"],
                limit=1,
                items_view="notLoaded",
            )
            if not turns:
                raise WakectlError("thread has no turns")
            latest = turns[0]
            if not isinstance(latest, dict):
                raise WakectlError("app-server returned invalid latest turn")
            latest_turn_id = latest.get("id")
            if not isinstance(latest_turn_id, str) or not latest_turn_id:
                raise WakectlError("app-server returned latest turn without an id")
            resolved = dict(condition)
            resolved["turnId"] = latest_turn_id
            return resolved

        turns, found = await turns_through_cursor(
            app,
            condition["threadId"],
            exact_turn_id,
        )
        if not found:
            raise WakectlError(f"turn not found: {exact_turn_id}")
        return condition

    turns = await list_thread_turns(
        app,
        condition["threadId"],
        limit=1,
        items_view="notLoaded",
    )
    return with_turn_cursor(condition, turns[0] if turns else None)


async def turns_through_cursor(
    app: Any,
    thread_id: str,
    cursor_id: str | None,
) -> tuple[list[dict[str, Any]], bool]:
    cursor: str | None = None
    seen_cursors: set[str] = set()
    turns: list[dict[str, Any]] = []
    while True:
        page = await list_turn_page(
            app,
            thread_id,
            cursor=cursor,
            limit=50,
            items_view="notLoaded",
        )
        batch = [turn for turn in page["data"] if isinstance(turn, dict)]
        turns.extend(batch)
        if cursor_id is None or any(turn.get("id") == cursor_id for turn in batch):
            return turns, True
        next_cursor = page.get("nextCursor")
        if next_cursor is None:
            return turns, False
        if not isinstance(next_cursor, str) or next_cursor in seen_cursors:
            raise WakectlError("app-server returned an invalid turn cursor")
        seen_cursors.add(next_cursor)
        cursor = next_cursor


def completed_turn_after_cursor(
    turns: list[dict[str, Any]],
    cursor_id: str | None,
    cursor_status: str | None,
) -> dict[str, Any] | None:
    if not turns:
        return None

    if cursor_id is None:
        return next(
            (
                turn
                for turn in turns
                if turn.get("status") in TERMINAL_TURN_STATUSES
            ),
            None,
        )

    cursor_index = next(
        (index for index, turn in enumerate(turns) if turn.get("id") == cursor_id),
        None,
    )
    if cursor_index is None:
        return None
    candidates = turns[:cursor_index]
    cursor = turns[cursor_index]
    if (
        cursor_status == "inProgress"
        and cursor.get("status") in TERMINAL_TURN_STATUSES
    ):
        candidates = [*candidates, cursor]

    return next(
        (turn for turn in candidates if turn.get("status") in TERMINAL_TURN_STATUSES),
        None,
    )


async def stop_condition_ready(
    app: Any,
    condition: dict[str, Any],
) -> tuple[bool, dict[str, Any], str]:
    exact_turn_id = condition.get("turnId")
    if exact_turn_id is not None:
        turns, found = await turns_through_cursor(
            app,
            condition["threadId"],
            exact_turn_id,
        )
        if not found:
            return False, {"status": "failed"}, f"turn no longer exists: {exact_turn_id}"
        turn = next(turn for turn in turns if turn.get("id") == exact_turn_id)
        status = turn.get("status", "unknown")
        if status in TERMINAL_TURN_STATUSES:
            return True, {}, f"turn {exact_turn_id} {status}"
        return False, {}, f"turn {exact_turn_id} is {status}"

    if "cursorTurnId" not in condition:
        turns = await list_thread_turns(
            app,
            condition["threadId"],
            limit=1,
            items_view="notLoaded",
        )
        latest = turns[0] if turns else None
        legacy_observed_active = bool(condition.get("observedActive"))
        updated = with_turn_cursor(condition, latest)
        if (
            legacy_observed_active
            and latest is not None
            and latest.get("status") in TERMINAL_TURN_STATUSES
        ):
            return True, {"condition": updated}, "thread stopped"
        return False, {"condition": updated}, "waiting for turn completion"

    turns, cursor_found = await turns_through_cursor(
        app,
        condition["threadId"],
        condition.get("cursorTurnId"),
    )
    latest = turns[0] if turns else None
    if not cursor_found:
        return (
            False,
            {"status": "failed"},
            f"turn cursor no longer exists: {condition.get('cursorTurnId')}",
        )

    completed = completed_turn_after_cursor(
        turns,
        condition.get("cursorTurnId"),
        condition.get("cursorTurnStatus"),
    )
    updated = with_turn_cursor(condition, latest)
    condition_updates = {} if updated == condition else {"condition": updated}
    if completed is not None:
        status = completed.get("status", "stopped")
        return True, {"condition": updated}, f"turn {completed.get('id')} {status}"
    if latest is None:
        return False, condition_updates, "waiting for first turn"
    status = latest.get("status", "unknown")
    if (
        latest.get("id") == condition.get("cursorTurnId")
        and status in TERMINAL_TURN_STATUSES
    ):
        return False, condition_updates, f"waiting for a later turn; cursor turn is {status}"
    reason = f"waiting for turn {latest.get('id')} to stop; status is {status}"
    return False, condition_updates, reason


async def condition_ready(
    app: Any | None,
    condition: dict[str, Any],
    job: dict[str, Any] | None = None,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[bool, dict[str, Any], str]:
    kind = condition["type"]
    if kind == "time":
        return time_condition_ready(condition)
    if kind == "cmd":
        return cmd_condition_ready(condition, timeout)
    if kind == "goal":
        if app is None:
            raise WakectlError("goal condition requires app-server")
        return await goal_condition_ready(app, condition, job)
    if kind == "stop":
        if app is None:
            raise WakectlError("stop condition requires app-server")
        stored = (job or {}).get("condition")
        effective = stored if isinstance(stored, dict) else condition
        return await stop_condition_ready(app, effective)
    raise WakectlError(f"unknown condition type: {kind}")


def condition_repeats(condition: dict[str, Any]) -> bool:
    return (
        "tokensUsedEvery" in condition
        or "timeUsedEvery" in condition
        or (condition.get("type") == "stop" and bool(condition.get("repeat")))
    )


def condition_needs_app(condition: dict[str, Any]) -> bool:
    return condition["type"] in {"goal", "stop"}


def max_fires_reached(condition: dict[str, Any], fire_count: int) -> bool:
    max_fires = condition.get("maxFires")
    return max_fires is not None and fire_count >= int(max_fires)


def new_job(
    condition: dict[str, Any],
    target: str,
    action: dict[str, Any],
    endpoint: str,
    *,
    timeout: float | None = None,
) -> dict[str, Any]:
    ts = now_seconds()
    job: dict[str, Any] = {
        "id": uuid.uuid4().hex[:12],
        "status": "pending",
        "condition": condition,
        "targetThreadId": target,
        "action": action,
        "endpoint": endpoint,
        "createdAt": ts,
        "updatedAt": ts,
        "fireCount": 0,
    }
    if timeout is not None:
        job["timeout"] = timeout
    if "tokensUsedEvery" in condition:
        job["lastTokensUsedBucket"] = 0
    if "timeUsedEvery" in condition:
        job["lastTimeUsedBucket"] = 0
    return job


def build_time_condition(args: argparse.Namespace) -> dict[str, Any]:
    if args.after is None and args.at is None:
        raise WakectlError("time condition requires --after or --at")
    if args.after is not None and args.at is not None:
        raise WakectlError("use only one of --after or --at")
    at = now_seconds() + args.after if args.after is not None else args.at
    return {"type": "time", "at": at}


def build_goal_condition(args: argparse.Namespace) -> dict[str, Any]:
    condition: dict[str, Any] = {"type": "goal", "threadId": args.thread_id}
    if args.status:
        condition["statuses"] = args.status
    if args.tokens_left_lte is not None:
        condition["tokensLeftLte"] = args.tokens_left_lte
    if args.tokens_used_gte is not None:
        condition["tokensUsedGte"] = args.tokens_used_gte
    if args.tokens_used_every is not None:
        condition["tokensUsedEvery"] = args.tokens_used_every
    if args.time_used_gte is not None:
        condition["timeUsedGte"] = args.time_used_gte
    if args.time_used_every is not None:
        condition["timeUsedEvery"] = args.time_used_every
    if getattr(args, "max_fires", None) is not None:
        condition["maxFires"] = args.max_fires

    predicate_count = len(condition) - 2 - int("maxFires" in condition)
    if predicate_count == 0:
        raise WakectlError("goal condition requires at least one predicate")
    every_count = int("tokensUsedEvery" in condition) + int("timeUsedEvery" in condition)
    if every_count > 1:
        raise WakectlError("use only one repeating goal predicate per wake")
    if "maxFires" in condition and every_count == 0:
        raise WakectlError("--max-fires requires a repeating goal predicate")
    return condition


def build_cmd_condition(args: argparse.Namespace) -> dict[str, Any]:
    argv = list(args.argv)
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        raise WakectlError("cmd condition requires a command after --")
    return {"type": "cmd", "argv": argv, "cwd": os.getcwd()}


def build_stop_condition(args: argparse.Namespace) -> dict[str, Any]:
    condition: dict[str, Any] = {
        "type": "stop",
        "threadId": args.thread_id,
    }
    exact_turn_id = getattr(args, "turn", None)
    if exact_turn_id is not None:
        condition["turnId"] = exact_turn_id
    if getattr(args, "repeat", False):
        if exact_turn_id is not None:
            raise WakectlError("--turn cannot be combined with --repeat")
        condition["repeat"] = True
    if getattr(args, "max_fires", None) is not None:
        if not condition.get("repeat"):
            raise WakectlError("--max-fires requires --repeat")
        condition["maxFires"] = args.max_fires
    return condition
