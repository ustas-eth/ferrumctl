from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
from typing import Any

from codex_threadctl.agents import (
    is_agent_path,
    resolve_agent_path,
    resolve_thread_reference,
)
from codex_threadctl.appserver import (
    AppServer,
    deliver_input,
    get_goal,
    normalize_endpoint,
)
from codex_threadctl.errors import (
    DeliveryUncertain,
    DirectInputUnsupported,
    ThreadNotLoaded,
    ThreadStateError,
)

from .conditions import (
    condition_needs_app,
    condition_ready,
    condition_repeats,
    max_fires_reached,
    new_job,
    seed_stop_condition,
)
from .constants import (
    CLIENT_VERSION,
    DELIVERY_LEASE_TIMEOUTS,
    SYSTEMD_SERVICE_NAME,
    SYSTEMD_TIMER_NAME,
)
from .errors import WakectlError
from .parsing import now_seconds
from .state import (
    cancel_job,
    claim_pending_jobs,
    insert_job,
    list_jobs,
    renew_claimed_job,
    update_claimed_job,
)
from .systemd import build_systemd_units, resolve_wakectl_bin, run_systemctl, systemd_user_dir


class LeaseLost(Exception):
    pass


_ADD_CMD_OPTIONS = {
    "--allow-active",
    "--endpoint",
    "--json",
    "--state",
    "--timeout",
    "--to",
    "--tree",
}


def wakectl_appserver(endpoint: str, timeout: float) -> AppServer:
    return AppServer(
        endpoint,
        timeout,
        client_name="codex_wakectl",
        client_title="codex-wakectl",
        client_version=CLIENT_VERSION,
    )


async def seed_goal_job(args: argparse.Namespace, job: dict[str, Any]) -> None:
    condition = job["condition"]
    if condition.get("type") != "goal":
        return
    async with wakectl_appserver(job["endpoint"], args.timeout) as app:
        goal = await get_goal(app, condition["threadId"])
    if goal is None:
        job["lastReason"] = "no goal while seeding watch"
        return
    created_at = goal.get("createdAt")
    if created_at is not None:
        condition["goalCreatedAt"] = created_at
    if "tokensUsedEvery" in condition:
        tokens_used = int(goal.get("tokensUsed") or 0)
        job["lastTokensUsedBucket"] = tokens_used // condition["tokensUsedEvery"]
    if "timeUsedEvery" in condition:
        time_used = int(goal.get("timeUsedSeconds") or 0)
        job["lastTimeUsedBucket"] = time_used // condition["timeUsedEvery"]


async def seed_stop_job(args: argparse.Namespace, job: dict[str, Any]) -> None:
    if job["condition"].get("type") != "stop":
        return
    async with wakectl_appserver(job["endpoint"], args.timeout) as app:
        job["condition"] = await seed_stop_condition(app, job["condition"])


async def resolve_condition_reference(
    app: AppServer,
    args: argparse.Namespace,
) -> None:
    thread_id = getattr(args, "thread_id", None)
    if isinstance(thread_id, str) and is_agent_path(thread_id):
        args.thread_id = await resolve_thread_reference(
            app,
            thread_id,
            tree_thread_id=getattr(args, "tree", None),
        )


async def resolve_add_references(args: argparse.Namespace) -> None:
    condition_path = getattr(args, "thread_id", None)
    target_path = args.to_thread_id
    if not any(
        isinstance(value, str) and is_agent_path(value)
        for value in (condition_path, target_path)
    ):
        return
    async with wakectl_appserver(args.endpoint, args.timeout) as app:
        await resolve_condition_reference(app, args)
        if is_agent_path(target_path):
            target = await resolve_agent_path(
                app,
                target_path,
                tree_thread_id=getattr(args, "tree", None),
            )
            if target["inputOwner"] == "parent":
                raise WakectlError(
                    f"parent-owned agent {target_path} cannot receive scheduled "
                    "input; target /root or another thread that accepts direct input"
                )
            args.to_thread_id = target["threadId"]


def _reject_misplaced_add_cmd_option(args: argparse.Namespace) -> None:
    if args.condition != "cmd" or not args.argv or args.argv[0] == "--":
        return
    option = args.argv[0].partition("=")[0]
    if option in _ADD_CMD_OPTIONS:
        raise WakectlError(f"{option} must appear before MESSAGE for add cmd")


async def cmd_add(args: argparse.Namespace) -> int:
    _reject_misplaced_add_cmd_option(args)
    await resolve_add_references(args)
    condition = args.condition_builder(args)
    endpoint = normalize_endpoint(args.endpoint)
    job = new_job(
        condition,
        args.to_thread_id,
        args.message,
        endpoint,
        allow_active=args.allow_active,
        timeout=args.timeout,
    )
    await seed_goal_job(args, job)
    await seed_stop_job(args, job)
    insert_job(args.state, job)
    if args.json:
        print(json.dumps({"job": job}, indent=2))
    else:
        print(job["id"])
    return 0


def cmd_moved(args: argparse.Namespace) -> int:
    raise WakectlError(f"command moved; use {args.moved_to}")


async def cmd_wait(args: argparse.Namespace) -> int:
    deadline = (
        time.monotonic() + args.max_wait
        if args.max_wait is not None
        else None
    )

    def timeout_result() -> int:
        reason = "maximum wait elapsed"
        if args.json:
            print(json.dumps({"ready": False, "reason": reason}, indent=2))
        else:
            print(reason, file=sys.stderr)
        return 1

    thread_id = getattr(args, "thread_id", None)
    if isinstance(thread_id, str) and is_agent_path(thread_id):

        async def resolve_once() -> None:
            async with wakectl_appserver(args.endpoint, args.timeout) as app:
                await resolve_condition_reference(app, args)

        if deadline is None:
            await resolve_once()
        else:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return timeout_result()
            try:
                await asyncio.wait_for(resolve_once(), timeout=remaining)
            except TimeoutError:
                return timeout_result()
    condition = args.condition_builder(args)
    job_state: dict[str, Any] = {}
    reason = "maximum wait elapsed"
    if condition["type"] == "stop":
        remaining = None if deadline is None else deadline - time.monotonic()
        if remaining is not None and remaining <= 0:
            return timeout_result()
        seed_timeout = (
            args.timeout if remaining is None else min(args.timeout, remaining)
        )

        async def seed_once() -> dict[str, Any]:
            async with wakectl_appserver(args.endpoint, seed_timeout) as app:
                return await seed_stop_condition(app, condition)

        try:
            if remaining is None:
                condition = await seed_once()
            else:
                condition = await asyncio.wait_for(seed_once(), timeout=remaining)
        except TimeoutError:
            return timeout_result()

    while True:
        remaining = None if deadline is None else deadline - time.monotonic()
        if remaining is not None and remaining <= 0:
            return timeout_result()
        predicate_timeout = (
            args.timeout if remaining is None else min(args.timeout, remaining)
        )

        async def check_once() -> tuple[bool, dict[str, Any], str]:
            if condition_needs_app(condition):
                async with wakectl_appserver(args.endpoint, predicate_timeout) as app:
                    return await condition_ready(
                        app,
                        condition,
                        job_state,
                        timeout=predicate_timeout,
                    )
            return await condition_ready(
                None,
                condition,
                job_state,
                timeout=predicate_timeout,
            )

        check = check_once()
        try:
            if remaining is None:
                ready, updates, reason = await check
            else:
                ready, updates, reason = await asyncio.wait_for(
                    check,
                    timeout=remaining,
                )
        except TimeoutError:
            return timeout_result()
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
        if updates.get("status") in {"failed", "superseded"}:
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


async def cmd_run(args: argparse.Namespace) -> int:
    fired: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    had_error = False
    owner, jobs = claim_pending_jobs(args.state, args.lease_seconds, args.limit)
    for job in jobs:
        try:
            endpoint = job.get("endpoint") or args.endpoint
            timeout = job["timeout"] if job.get("timeout") is not None else args.timeout
            allow_active = bool(job.get("allowActive"))
            lease_window = max(
                args.lease_seconds,
                math.ceil(timeout * DELIVERY_LEASE_TIMEOUTS) + 5,
            )
            if not renew_claimed_job(
                args.state,
                job["id"],
                owner,
                lease_window,
            ):
                raise LeaseLost("lease lost before condition check")

            if condition_needs_app(job["condition"]):
                async with wakectl_appserver(endpoint, timeout) as app:
                    ready, updates, reason = await condition_ready(
                        app,
                        job["condition"],
                        job,
                        timeout=timeout,
                    )
                    if ready:
                        if not renew_claimed_job(
                            args.state,
                            job["id"],
                            owner,
                            lease_window,
                        ):
                            raise LeaseLost("lease lost before delivery")
                        delivery = await deliver_input(
                            app,
                            job["targetThreadId"],
                            job["message"],
                            allow_active=allow_active,
                        )
                    else:
                        delivery = None
            else:
                ready, updates, reason = await condition_ready(
                    None,
                    job["condition"],
                    job,
                    timeout=timeout,
                )
                if ready:
                    if not renew_claimed_job(
                        args.state,
                        job["id"],
                        owner,
                        lease_window,
                    ):
                        raise LeaseLost("lease lost before delivery")
                    async with wakectl_appserver(endpoint, timeout) as app:
                        delivery = await deliver_input(
                            app,
                            job["targetThreadId"],
                            job["message"],
                            allow_active=allow_active,
                        )
                else:
                    delivery = None

            if not ready:
                pending_updates = dict(updates)
                pending_updates.update({"lastReason": reason, "lastError": None})
                committed = update_claimed_job(
                    args.state,
                    job["id"],
                    owner,
                    pending_updates,
                )
                if committed:
                    skipped.append(
                        {
                            "id": job["id"],
                            "status": pending_updates.get("status", "pending"),
                            "reason": reason,
                        }
                    )
                else:
                    had_error = True
                    skipped.append({"id": job["id"], "reason": "lease lost before update"})
                continue

            if delivery is None:
                raise WakectlError("condition was ready but input was not delivered")

            ts = now_seconds()
            next_fire_count = int(job.get("fireCount") or 0) + 1
            result_updates = dict(updates)
            result_updates.update(
                {
                    "fireCount": next_fire_count,
                    "lastFiredAt": ts,
                    "lastTurnId": delivery.get("turnId"),
                    "lastClientMessageId": delivery.get("clientMessageId"),
                    "lastDeliveryMode": delivery.get("delivery"),
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
                fired.append(
                    {
                        "id": job["id"],
                        "turnId": delivery.get("turnId"),
                        "delivery": delivery.get("delivery"),
                        "reason": reason,
                    }
                )
            else:
                had_error = True
                skipped.append({"id": job["id"], "reason": "lease lost after wake"})
        except DirectInputUnsupported as exc:
            had_error = True
            reason = str(exc)
            committed = update_claimed_job(
                args.state,
                job["id"],
                owner,
                {"status": "failed", "lastError": reason},
            )
            skipped.append(
                {
                    "id": job["id"],
                    "status": "failed",
                    "reason": reason if committed else "lease lost after rejection",
                }
            )
        except (ThreadNotLoaded, ThreadStateError) as exc:
            reason = str(exc)
            committed = update_claimed_job(
                args.state,
                job["id"],
                owner,
                {"lastReason": reason, "lastError": None},
            )
            if committed:
                skipped.append({"id": job["id"], "reason": reason})
            else:
                had_error = True
                skipped.append({"id": job["id"], "reason": "lease lost after deferral"})
        except DeliveryUncertain as exc:
            had_error = True
            reason = str(exc)
            committed = update_claimed_job(
                args.state,
                job["id"],
                owner,
                {
                    "status": "uncertain",
                    "lastTurnId": exc.turn_id,
                    "lastClientMessageId": exc.client_message_id,
                    "lastError": reason,
                },
            )
            skipped.append(
                {
                    "id": job["id"],
                    "reason": reason if committed else "lease lost after uncertain delivery",
                }
            )
        except LeaseLost as exc:
            had_error = True
            skipped.append({"id": job["id"], "reason": str(exc)})
        except Exception as exc:
            had_error = True
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
            print(
                f"fired\t{item['id']}\t{item.get('turnId') or '-'}"
                f"\t{item.get('delivery') or '-'}"
            )
        for item in skipped:
            print(
                f"{item.get('status', 'pending')}\t{item['id']}\t{item['reason']}",
                file=sys.stderr,
            )
    return 1 if had_error else 0


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
                        job.get("lastError") or job.get("lastReason") or "-",
                    ]
                )
            )
    return 0


def cmd_cancel(args: argparse.Namespace) -> int:
    if not cancel_job(args.state, args.job_id):
        raise WakectlError(
            f"job is unknown, terminal, or currently claimed: {args.job_id}"
        )
    if args.json:
        print(json.dumps({"canceled": args.job_id}, indent=2))
    else:
        print("canceled")
    return 0


def cmd_systemd_install(args: argparse.Namespace) -> int:
    unit_dir = systemd_user_dir()
    service_path = unit_dir / SYSTEMD_SERVICE_NAME
    timer_path = unit_dir / SYSTEMD_TIMER_NAME
    state = args.state.expanduser().resolve()
    service, timer = build_systemd_units(
        wakectl_bin=resolve_wakectl_bin(),
        state=state,
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
                    "state": str(state),
                    "enabled": True,
                    "started": True,
                },
                indent=2,
            )
        )
    else:
        print(f"installed\t{service_path}")
        print(f"installed\t{timer_path}")
        print(f"state\t{state}")
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
