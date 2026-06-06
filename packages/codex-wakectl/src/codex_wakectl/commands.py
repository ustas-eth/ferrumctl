from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from typing import Any

from .appserver import AppServer, get_goal, get_thread_status, list_loaded, send_turn, status_name
from .conditions import (
    condition_needs_app,
    condition_ready,
    condition_repeats,
    max_fires_reached,
    new_job,
)
from .constants import SYSTEMD_SERVICE_NAME, SYSTEMD_TIMER_NAME
from .errors import WakectlError
from .parsing import now_seconds
from .state import cancel_job, claim_pending_jobs, insert_job, list_jobs, update_claimed_job
from .systemd import build_systemd_units, resolve_wakectl_bin, run_systemctl, systemd_user_dir


async def cmd_loaded(args: argparse.Namespace) -> int:
    async with AppServer(args.endpoint, args.timeout) as app:
        ids = await list_loaded(app)
    if args.json:
        print(json.dumps({"threads": ids}, indent=2))
    else:
        for thread_id in ids:
            print(thread_id)
    return 0


async def cmd_status(args: argparse.Namespace) -> int:
    async with AppServer(args.endpoint, args.timeout) as app:
        loaded = await list_loaded(app)
        status = await get_thread_status(app, args.thread_id)
    result = {
        "threadId": args.thread_id,
        "loaded": args.thread_id in loaded,
        "status": status,
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        loaded_label = "loaded" if result["loaded"] else "not-loaded"
        print(f"{loaded_label}\t{status_name(status)}\t{args.thread_id}")
    return 0


async def cmd_send(args: argparse.Namespace) -> int:
    async with AppServer(args.endpoint, args.timeout) as app:
        turn = await send_turn(
            app,
            args.thread_id,
            args.message,
            allow_active=args.allow_active,
        )
    if args.json:
        print(json.dumps({"turn": turn}, indent=2))
    else:
        print(turn.get("id", "sent"))
    return 0


async def seed_repeating_goal_job(args: argparse.Namespace, job: dict[str, Any]) -> None:
    condition = job["condition"]
    if condition.get("type") != "goal" or not condition_repeats(condition):
        return
    try:
        async with AppServer(args.endpoint, args.timeout) as app:
            goal = await get_goal(app, condition["threadId"])
    except Exception as exc:
        job["lastError"] = f"could not seed interval bucket: {exc}"
        return
    if goal is None:
        job["lastReason"] = "no goal while seeding interval bucket"
        return
    if "tokensUsedEvery" in condition:
        tokens_used = int(goal.get("tokensUsed") or 0)
        job["lastTokensUsedBucket"] = tokens_used // condition["tokensUsedEvery"]
    if "timeUsedEvery" in condition:
        time_used = int(goal.get("timeUsedSeconds") or 0)
        job["lastTimeUsedBucket"] = time_used // condition["timeUsedEvery"]


async def cmd_add(args: argparse.Namespace) -> int:
    condition = args.condition_builder(args)
    job = new_job(
        condition,
        args.to_thread_id,
        args.message,
        args.endpoint,
        allow_active=args.allow_active,
        timeout=args.timeout,
    )
    await seed_repeating_goal_job(args, job)
    insert_job(args.state, job)
    if args.json:
        print(json.dumps({"job": job}, indent=2))
    else:
        print(job["id"])
    return 0


async def cmd_wait(args: argparse.Namespace) -> int:
    condition = args.condition_builder(args)
    deadline = time.monotonic() + args.max_wait if args.max_wait is not None else None
    app_cm: Any = AppServer(args.endpoint, args.timeout) if condition_needs_app(condition) else None
    app = await app_cm.__aenter__() if app_cm is not None else None
    job_state: dict[str, Any] = {}
    try:
        while True:
            ready, updates, reason = await condition_ready(
                app,
                condition,
                job_state,
                timeout=args.timeout,
            )
            if ready:
                if args.json:
                    print(
                        json.dumps(
                            {"ready": True, "reason": reason, "updates": updates},
                            indent=2,
                        )
                    )
                else:
                    print(reason)
                return 0
            job_state.update(updates)
            if "condition" in updates:
                condition = updates["condition"]
            if deadline is not None and time.monotonic() >= deadline:
                if args.json:
                    print(json.dumps({"ready": False, "reason": reason}, indent=2))
                else:
                    print(reason, file=sys.stderr)
                return 1
            sleep_for = args.poll_interval
            if condition["type"] == "time":
                sleep_for = min(sleep_for, max(0.0, condition["at"] - now_seconds()))
            if deadline is not None:
                sleep_for = min(sleep_for, max(0.0, deadline - time.monotonic()))
            await asyncio.sleep(max(0.1, sleep_for))
    finally:
        if app_cm is not None:
            await app_cm.__aexit__(None, None, None)


async def cmd_run(args: argparse.Namespace) -> int:
    fired: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    owner, jobs = claim_pending_jobs(args.state, args.lease_seconds, args.limit)
    for job in jobs:
        try:
            endpoint = job.get("endpoint") or args.endpoint
            timeout = job["timeout"] if job.get("timeout") is not None else args.timeout
            allow_active = bool(job.get("allowActive"))
            if condition_needs_app(job["condition"]):
                async with AppServer(endpoint, timeout) as app:
                    ready, updates, reason = await condition_ready(
                        app,
                        job["condition"],
                        job,
                        timeout=timeout,
                    )
                    turn = (
                        await send_turn(
                            app,
                            job["targetThreadId"],
                            job["message"],
                            allow_active=allow_active,
                        )
                        if ready
                        else None
                    )
            else:
                ready, updates, reason = await condition_ready(
                    None,
                    job["condition"],
                    job,
                    timeout=timeout,
                )
                if ready:
                    async with AppServer(endpoint, timeout) as app:
                        turn = await send_turn(
                            app,
                            job["targetThreadId"],
                            job["message"],
                            allow_active=allow_active,
                        )
                else:
                    turn = None

            if not ready:
                committed = update_claimed_job(
                    args.state,
                    job["id"],
                    owner,
                    {"lastReason": reason, "lastError": None},
                )
                if committed:
                    skipped.append({"id": job["id"], "reason": reason})
                else:
                    skipped.append({"id": job["id"], "reason": "lease lost before update"})
                continue

            ts = now_seconds()
            next_fire_count = int(job.get("fireCount") or 0) + 1
            result_updates = dict(updates)
            result_updates.update(
                {
                    "fireCount": next_fire_count,
                    "lastFiredAt": ts,
                    "lastTurnId": turn.get("id"),
                    "lastReason": reason,
                    "lastError": None,
                }
            )
            effective_condition = result_updates.get("condition", job["condition"])
            if not condition_repeats(effective_condition) or max_fires_reached(
                effective_condition,
                next_fire_count,
            ):
                result_updates["status"] = "fired"
                result_updates["firedAt"] = ts
            committed = update_claimed_job(args.state, job["id"], owner, result_updates)
            if committed:
                fired.append({"id": job["id"], "turnId": turn.get("id"), "reason": reason})
            else:
                skipped.append({"id": job["id"], "reason": "lease lost after wake"})
        except Exception as exc:
            reason = str(exc)
            committed = update_claimed_job(
                args.state,
                job["id"],
                owner,
                {"lastError": reason},
            )
            if committed:
                skipped.append({"id": job["id"], "reason": reason})
            else:
                skipped.append({"id": job["id"], "reason": "lease lost after error"})

    if args.json:
        print(json.dumps({"fired": fired, "skipped": skipped}, indent=2))
    else:
        for item in fired:
            print(f"fired\t{item['id']}\t{item.get('turnId') or '-'}")
        for item in skipped:
            print(f"pending\t{item['id']}\t{item['reason']}", file=sys.stderr)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    selected = list_jobs(args.state, include_all=args.all)
    if args.json:
        print(json.dumps({"jobs": selected}, indent=2))
    else:
        for job in selected:
            print(
                "\t".join(
                    [
                        job["id"],
                        job.get("status", "-"),
                        job["condition"]["type"],
                        job.get("targetThreadId", "-"),
                        str(job.get("fireCount", 0)),
                        job.get("lastReason") or job.get("lastError") or "-",
                    ]
                )
            )
    return 0


def cmd_cancel(args: argparse.Namespace) -> int:
    if not cancel_job(args.state, args.job_id):
        raise WakectlError(f"unknown job id: {args.job_id}")
    if args.json:
        print(json.dumps({"canceled": args.job_id}, indent=2))
    else:
        print("canceled")
    return 0


def cmd_systemd_install(args: argparse.Namespace) -> int:
    unit_dir = systemd_user_dir()
    service_path = unit_dir / SYSTEMD_SERVICE_NAME
    timer_path = unit_dir / SYSTEMD_TIMER_NAME
    service, timer = build_systemd_units(
        wakectl_bin=resolve_wakectl_bin(),
        state=args.state,
        interval_seconds=args.interval,
    )

    unit_dir.mkdir(parents=True, exist_ok=True)
    service_path.write_text(service)
    timer_path.write_text(timer)
    run_systemctl(["daemon-reload"])
    run_systemctl(["enable", "--now", SYSTEMD_TIMER_NAME])

    if args.json:
        print(
            json.dumps(
                {
                    "service": str(service_path),
                    "timer": str(timer_path),
                    "enabled": True,
                    "started": True,
                },
                indent=2,
            )
        )
    else:
        print(f"installed\t{service_path}")
        print(f"installed\t{timer_path}")
        print(f"started\t{SYSTEMD_TIMER_NAME}")
    return 0


def cmd_systemd_uninstall(args: argparse.Namespace) -> int:
    unit_dir = systemd_user_dir()
    service_path = unit_dir / SYSTEMD_SERVICE_NAME
    timer_path = unit_dir / SYSTEMD_TIMER_NAME

    run_systemctl(["disable", "--now", SYSTEMD_TIMER_NAME], check=False)
    removed: list[str] = []
    for path in [service_path, timer_path]:
        if path.exists():
            path.unlink()
            removed.append(str(path))
    run_systemctl(["daemon-reload"])

    if args.json:
        print(json.dumps({"removed": removed}, indent=2))
    else:
        for path in removed:
            print(f"removed\t{path}")
        if not removed:
            print("removed\t-")
    return 0
