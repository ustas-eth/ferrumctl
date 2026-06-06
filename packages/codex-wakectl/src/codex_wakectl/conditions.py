from __future__ import annotations

import argparse
import os
import subprocess
import uuid
from typing import Any

from .appserver import get_goal, get_thread_status, status_name, thread_is_active
from .constants import DEFAULT_TIMEOUT
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

    statuses = condition.get("statuses")
    if statuses and goal.get("status") not in statuses:
        return False, {}, f"status is {goal.get('status')}"

    tokens_used = int(goal.get("tokensUsed") or 0)
    token_budget = goal.get("tokenBudget")
    time_used = int(goal.get("timeUsedSeconds") or 0)

    if "tokensLeftLte" in condition:
        if token_budget is None:
            return False, {}, "goal has no token budget"
        tokens_left = int(token_budget) - tokens_used
        if tokens_left > condition["tokensLeftLte"]:
            return False, {}, f"tokens left {tokens_left}"

    if "tokensUsedGte" in condition and tokens_used < condition["tokensUsedGte"]:
        return False, {}, f"tokens used {tokens_used}"

    if "timeUsedGte" in condition and time_used < condition["timeUsedGte"]:
        return False, {}, f"time used {time_used}s"

    if "tokensUsedEvery" in condition:
        interval = condition["tokensUsedEvery"]
        bucket = tokens_used // interval
        previous = int((job or {}).get("lastTokensUsedBucket") or 0)
        if bucket <= 0 or bucket <= previous:
            return False, {}, f"tokens used bucket {bucket}"
        return True, {"lastTokensUsedBucket": bucket}, f"tokens used {tokens_used}"

    if "timeUsedEvery" in condition:
        interval = condition["timeUsedEvery"]
        bucket = time_used // interval
        previous = int((job or {}).get("lastTimeUsedBucket") or 0)
        if bucket <= 0 or bucket <= previous:
            return False, {}, f"time used bucket {bucket}"
        return True, {"lastTimeUsedBucket": bucket}, f"time used {time_used}s"

    return True, {}, "goal predicate matched"


async def stop_condition_ready(
    app: Any,
    condition: dict[str, Any],
) -> tuple[bool, dict[str, Any], str]:
    status = await get_thread_status(app, condition["threadId"])
    name = status_name(status)
    observed_active = bool(condition.get("observedActive"))
    updated = dict(condition)
    updated["lastStatus"] = name

    if thread_is_active(status):
        if not observed_active:
            updated["observedActive"] = True
            return False, {"condition": updated}, f"status is {name}"
        return False, {}, f"status is {name}"

    if name != "idle":
        if condition.get("lastStatus") != name:
            return False, {"condition": updated}, f"status is {name}"
        return False, {}, f"status is {name}"

    if observed_active:
        if condition.get("repeat"):
            updated["observedActive"] = False
            return True, {"condition": updated}, "thread stopped"
        return True, {}, "thread stopped"

    if condition.get("lastStatus") != name:
        updated["observedActive"] = False
        return False, {"condition": updated}, "waiting for active turn"
    return False, {}, "waiting for active turn"


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
    message: str,
    endpoint: str,
    *,
    allow_active: bool = False,
    timeout: float | None = None,
) -> dict[str, Any]:
    ts = now_seconds()
    job: dict[str, Any] = {
        "id": uuid.uuid4().hex[:12],
        "status": "pending",
        "condition": condition,
        "targetThreadId": target,
        "message": message,
        "endpoint": endpoint,
        "allowActive": allow_active,
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
        "observedActive": False,
    }
    if getattr(args, "repeat", False):
        condition["repeat"] = True
    if getattr(args, "max_fires", None) is not None:
        if not condition.get("repeat"):
            raise WakectlError("--max-fires requires --repeat")
        condition["maxFires"] = args.max_fires
    return condition
