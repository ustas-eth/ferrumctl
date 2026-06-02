from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import AbstractContextManager
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import websockets


DEFAULT_TIMEOUT = 20.0
CLIENT_VERSION = "0.1.0"
STATUS_VALUES = {
    "active",
    "paused",
    "blocked",
    "budgetLimited",
    "usageLimited",
    "complete",
}
DURATION_RE = re.compile(r"^([0-9][0-9_]*)([smhd])$")


class WakectlError(RuntimeError):
    pass


class AppServer:
    def __init__(self, endpoint: str, timeout: float):
        self.endpoint = endpoint
        self.timeout = timeout
        self.next_id = 1
        self.ws: Any = None

    async def __aenter__(self) -> "AppServer":
        self.ws = await connect_websocket(self.endpoint)
        await self.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "codex_wakectl",
                    "title": "codex-wakectl",
                    "version": CLIENT_VERSION,
                },
                "capabilities": {"experimentalApi": True},
            },
        )
        await self.notify("initialized", {})
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self.ws is not None:
            await self.ws.close()

    async def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        request_id = self.next_id
        self.next_id += 1
        msg: dict[str, Any] = {"method": method, "id": request_id}
        if params is not None:
            msg["params"] = params
        await self.ws.send(json.dumps(msg, separators=(",", ":")))
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=0.2)
            except TimeoutError:
                continue
            msg = json.loads(raw)
            if msg.get("id") != request_id:
                continue
            if "error" in msg:
                raise WakectlError(json.dumps(msg["error"], separators=(",", ":")))
            return msg.get("result")
        raise WakectlError(f"timed out waiting for app-server method {method}")

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        msg: dict[str, Any] = {"method": method}
        if params is not None:
            msg["params"] = params
        await self.ws.send(json.dumps(msg, separators=(",", ":")))


async def connect_websocket(endpoint: str) -> Any:
    if endpoint.startswith("unix://"):
        socket_path = resolve_unix_endpoint(endpoint)
        return await websockets.unix_connect(
            socket_path,
            uri="ws://localhost/rpc",
            compression=None,
            user_agent_header=None,
        )
    parsed = urlparse(endpoint)
    if parsed.scheme != "ws":
        raise WakectlError("endpoint must be unix://, unix://PATH, or ws://HOST:PORT")
    return await websockets.connect(
        endpoint,
        compression=None,
        user_agent_header=None,
    )


def resolve_unix_endpoint(endpoint: str) -> str:
    raw = endpoint.removeprefix("unix://")
    if not raw:
        codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        return str(codex_home / "app-server-control" / "app-server-control.sock")
    path = Path(raw)
    if not path.is_absolute():
        path = Path.cwd() / path
    return str(path)


class StateStore(AbstractContextManager["StateStore"]):
    def __init__(self, path: Path):
        self.path = path
        self.lock_path = path.with_suffix(path.suffix + ".lock")
        self.lock_file: Any = None
        self.data: dict[str, Any] = {"version": 1, "jobs": []}

    def __enter__(self) -> "StateStore":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_file = self.lock_path.open("a+")
        fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX)
        if self.path.exists():
            with self.path.open() as f:
                self.data = json.load(f)
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self.lock_file is not None:
            fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_UN)
            self.lock_file.close()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=self.path.name + ".",
            suffix=".tmp",
            dir=self.path.parent,
            text=True,
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(self.data, f, indent=2, sort_keys=True)
                f.write("\n")
            os.replace(tmp_name, self.path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)


def default_state_path() -> Path:
    root = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return root / "codex-wakectl" / "jobs.json"


def now_seconds() -> int:
    return int(time.time())


def parse_duration(value: str) -> int:
    match = DURATION_RE.match(value)
    if not match:
        raise argparse.ArgumentTypeError("must be an integer duration with unit s, m, h, or d")
    number = int(match.group(1).replace("_", ""))
    unit = match.group(2)
    scale = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
    if number <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return number * scale


def parse_positive_int(value: str) -> int:
    try:
        parsed = int(value.replace("_", ""))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def parse_at(value: str) -> int:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be ISO timestamp with timezone") from exc
    if dt.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp must include timezone, e.g. Z or +00:00")
    return int(dt.timestamp())


def parse_statuses(value: str) -> list[str]:
    statuses = [part.strip() for part in value.split(",") if part.strip()]
    unknown = [status for status in statuses if status not in STATUS_VALUES]
    if unknown:
        raise argparse.ArgumentTypeError(
            "unknown goal status: " + ", ".join(sorted(unknown))
        )
    if not statuses:
        raise argparse.ArgumentTypeError("must include at least one status")
    return statuses


def format_time(ts: int | None) -> str:
    if ts is None:
        return "-"
    return datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")


async def list_loaded(app: AppServer) -> list[str]:
    ids: list[str] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {}
        if cursor is not None:
            params["cursor"] = cursor
        result = await app.request("thread/loaded/list", params)
        ids.extend(result.get("data", []))
        cursor = result.get("nextCursor")
        if cursor is None:
            return ids


async def get_thread_status(app: AppServer, thread_id: str) -> dict[str, Any]:
    result = await app.request(
        "thread/read",
        {"threadId": thread_id, "includeTurns": False},
    )
    return result["thread"].get("status", {"type": "unknown"})


def status_name(status: dict[str, Any]) -> str:
    return str(status.get("type", "unknown"))


async def send_turn(
    app: AppServer,
    thread_id: str,
    message: str,
    *,
    allow_active: bool = False,
) -> dict[str, Any]:
    loaded = await list_loaded(app)
    if thread_id not in loaded:
        raise WakectlError(f"thread is not loaded on this app-server: {thread_id}")
    status = await get_thread_status(app, thread_id)
    name = status_name(status)
    if name != "idle" and not allow_active:
        raise WakectlError(f"thread is {name}; refusing to start overlapping turn")
    result = await app.request(
        "turn/start",
        {
            "threadId": thread_id,
            "input": [
                {
                    "type": "text",
                    "text": message,
                    "textElements": [],
                }
            ],
        },
    )
    return result["turn"]


async def get_goal(app: AppServer, thread_id: str) -> dict[str, Any] | None:
    result = await app.request("thread/goal/get", {"threadId": thread_id})
    return result.get("goal")


def time_condition_ready(condition: dict[str, Any]) -> tuple[bool, dict[str, Any], str]:
    ready = now_seconds() >= condition["at"]
    return ready, {}, "ready" if ready else f"waiting until {format_time(condition['at'])}"


def cmd_condition_ready(condition: dict[str, Any]) -> tuple[bool, dict[str, Any], str]:
    proc = subprocess.run(
        condition["argv"],
        cwd=condition.get("cwd") or None,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if proc.returncode == 0:
        return True, {}, "command exited 0"
    return False, {}, f"command exited {proc.returncode}"


async def goal_condition_ready(
    app: AppServer,
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


async def condition_ready(
    app: AppServer | None,
    condition: dict[str, Any],
    job: dict[str, Any] | None = None,
) -> tuple[bool, dict[str, Any], str]:
    kind = condition["type"]
    if kind == "time":
        return time_condition_ready(condition)
    if kind == "cmd":
        return cmd_condition_ready(condition)
    if kind == "goal":
        if app is None:
            raise WakectlError("goal condition requires app-server")
        return await goal_condition_ready(app, condition, job)
    raise WakectlError(f"unknown condition type: {kind}")


def condition_repeats(condition: dict[str, Any]) -> bool:
    return "tokensUsedEvery" in condition or "timeUsedEvery" in condition


def new_job(condition: dict[str, Any], target: str, message: str, endpoint: str) -> dict[str, Any]:
    ts = now_seconds()
    job: dict[str, Any] = {
        "id": uuid.uuid4().hex[:12],
        "status": "pending",
        "condition": condition,
        "targetThreadId": target,
        "message": message,
        "endpoint": endpoint,
        "createdAt": ts,
        "updatedAt": ts,
        "fireCount": 0,
    }
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

    predicate_count = len(condition) - 2
    if predicate_count == 0:
        raise WakectlError("goal condition requires at least one predicate")
    every_count = int("tokensUsedEvery" in condition) + int("timeUsedEvery" in condition)
    if every_count > 1:
        raise WakectlError("use only one repeating goal predicate per wake")
    return condition


def build_cmd_condition(args: argparse.Namespace) -> dict[str, Any]:
    argv = list(args.argv)
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        raise WakectlError("cmd condition requires a command after --")
    return {"type": "cmd", "argv": argv, "cwd": os.getcwd()}


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
    job = new_job(condition, args.to_thread_id, args.message, args.endpoint)
    await seed_repeating_goal_job(args, job)
    with StateStore(args.state) as store:
        store.data.setdefault("jobs", []).append(job)
        store.save()
    if args.json:
        print(json.dumps({"job": job}, indent=2))
    else:
        print(job["id"])
    return 0


async def cmd_wait(args: argparse.Namespace) -> int:
    condition = args.condition_builder(args)
    deadline = time.monotonic() + args.max_wait if args.max_wait is not None else None
    app_cm: Any = AppServer(args.endpoint, args.timeout) if condition["type"] == "goal" else None
    app = await app_cm.__aenter__() if app_cm is not None else None
    job_state: dict[str, Any] = {}
    try:
        while True:
            ready, updates, reason = await condition_ready(app, condition, job_state)
            if ready:
                if args.json:
                    print(json.dumps({"ready": True, "reason": reason, "updates": updates}, indent=2))
                else:
                    print(reason)
                return 0
            job_state.update(updates)
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


async def cmd_tick(args: argparse.Namespace) -> int:
    fired: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    with StateStore(args.state) as store:
        pending = [job for job in store.data.get("jobs", []) if job.get("status") == "pending"]
        for job in pending:
            if args.limit is not None and len(fired) >= args.limit:
                break
            try:
                endpoint = job.get("endpoint") or args.endpoint
                if job["condition"]["type"] == "goal":
                    async with AppServer(endpoint, args.timeout) as app:
                        ready, updates, reason = await condition_ready(app, job["condition"], job)
                        if ready:
                            turn = await send_turn(
                                app,
                                job["targetThreadId"],
                                job["message"],
                                allow_active=args.allow_active,
                            )
                        else:
                            turn = None
                else:
                    ready, updates, reason = await condition_ready(None, job["condition"], job)
                    if ready:
                        async with AppServer(endpoint, args.timeout) as app:
                            turn = await send_turn(
                                app,
                                job["targetThreadId"],
                                job["message"],
                                allow_active=args.allow_active,
                            )
                    else:
                        turn = None

                if not ready:
                    job["lastReason"] = reason
                    job["updatedAt"] = now_seconds()
                    skipped.append({"id": job["id"], "reason": reason})
                    continue
                ts = now_seconds()
                job.update(updates)
                job["fireCount"] = int(job.get("fireCount") or 0) + 1
                job["lastFiredAt"] = ts
                job["lastTurnId"] = turn.get("id")
                job["lastReason"] = reason
                job["lastError"] = None
                job["updatedAt"] = ts
                if not condition_repeats(job["condition"]):
                    job["status"] = "fired"
                    job["firedAt"] = ts
                fired.append({"id": job["id"], "turnId": turn.get("id"), "reason": reason})
            except Exception as exc:
                job["lastError"] = str(exc)
                job["updatedAt"] = now_seconds()
                skipped.append({"id": job["id"], "reason": str(exc)})
        store.save()

    if args.json:
        print(json.dumps({"fired": fired, "skipped": skipped}, indent=2))
    else:
        for item in fired:
            print(f"fired\t{item['id']}\t{item.get('turnId') or '-'}")
        for item in skipped:
            print(f"pending\t{item['id']}\t{item['reason']}", file=sys.stderr)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    with StateStore(args.state) as store:
        jobs = list(store.data.get("jobs", []))
    if args.all:
        selected = jobs
    else:
        selected = [job for job in jobs if job.get("status") == "pending"]
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
    canceled = False
    with StateStore(args.state) as store:
        for job in store.data.get("jobs", []):
            if job.get("id") == args.job_id:
                job["status"] = "canceled"
                job["updatedAt"] = now_seconds()
                canceled = True
                break
        store.save()
    if not canceled:
        raise WakectlError(f"unknown job id: {args.job_id}")
    if args.json:
        print(json.dumps({"canceled": args.job_id}, indent=2))
    else:
        print("canceled")
    return 0


def add_global_options(parser: argparse.ArgumentParser, *, defaults: bool) -> None:
    parser.add_argument(
        "--endpoint",
        default="unix://" if defaults else argparse.SUPPRESS,
        help="app-server endpoint: unix://, unix://PATH, or ws://HOST:PORT",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT if defaults else argparse.SUPPRESS,
        help="app-server request timeout in seconds",
    )
    parser.add_argument(
        "--state",
        type=Path,
        default=default_state_path() if defaults else argparse.SUPPRESS,
        help="wake job state file",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False if defaults else argparse.SUPPRESS,
        help="print JSON output",
    )


def add_target_message(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--to", dest="to_thread_id", required=True, help="thread to wake")
    parser.add_argument("message", help="message to send when the wake fires")


def add_time_condition_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser("time", help="time-based condition")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--after", type=parse_duration, help="duration such as 10m or 2h")
    group.add_argument("--at", type=parse_at, help="ISO timestamp with timezone")
    parser.set_defaults(condition_builder=build_time_condition)
    add_target_message(parser)
    add_global_options(parser, defaults=False)


def add_goal_condition_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("thread_id", help="goal thread to watch")
    parser.add_argument("--status", type=parse_statuses, help="comma-separated goal statuses")
    parser.add_argument("--tokens-left-lte", type=parse_positive_int)
    parser.add_argument("--tokens-used-gte", type=parse_positive_int)
    parser.add_argument("--tokens-used-every", type=parse_positive_int)
    parser.add_argument("--time-used-gte", type=parse_duration)
    parser.add_argument("--time-used-every", type=parse_duration)
    parser.set_defaults(condition_builder=build_goal_condition)


def add_goal_condition_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser("goal", help="goal-state condition")
    add_goal_condition_options(parser)
    add_target_message(parser)
    add_global_options(parser, defaults=False)


def add_cmd_condition_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser("cmd", help="shell command predicate")
    add_target_message(parser)
    parser.add_argument("argv", nargs=argparse.REMAINDER, help="command after --")
    parser.set_defaults(condition_builder=build_cmd_condition)
    add_global_options(parser, defaults=False)


def add_wait_options(parser: argparse.ArgumentParser, *, defaults: bool) -> None:
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=30.0 if defaults else argparse.SUPPRESS,
        help="seconds between condition checks",
    )
    parser.add_argument(
        "--max-wait",
        type=parse_duration,
        default=None if defaults else argparse.SUPPRESS,
        help="maximum time to wait",
    )


def add_wait_time_condition_parser(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = sub.add_parser("time", help="wait for time")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--after", type=parse_duration)
    group.add_argument("--at", type=parse_at)
    parser.set_defaults(condition_builder=build_time_condition)
    add_wait_options(parser, defaults=False)
    add_global_options(parser, defaults=False)


def add_wait_goal_condition_parser(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = sub.add_parser("goal", help="wait for goal")
    add_goal_condition_options(parser)
    add_wait_options(parser, defaults=False)
    add_global_options(parser, defaults=False)


def add_wait_cmd_condition_parser(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = sub.add_parser("cmd", help="wait for command predicate")
    parser.add_argument("argv", nargs=argparse.REMAINDER, help="command after --")
    parser.set_defaults(condition_builder=build_cmd_condition)
    add_wait_options(parser, defaults=False)
    add_global_options(parser, defaults=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codex-wakectl",
        description="Wake app-server-backed Codex threads now or when a condition is met.",
    )
    add_global_options(parser, defaults=True)
    sub = parser.add_subparsers(dest="command", required=True)

    loaded = sub.add_parser("loaded", help="list loaded thread ids")
    add_global_options(loaded, defaults=False)
    loaded.set_defaults(func=cmd_loaded)

    status = sub.add_parser("status", help="show loaded and active status for a thread")
    status.add_argument("thread_id")
    add_global_options(status, defaults=False)
    status.set_defaults(func=cmd_status)

    send = sub.add_parser("send", help="send an immediate wake turn")
    send.add_argument("thread_id")
    send.add_argument("message")
    send.add_argument("--allow-active", action="store_true")
    add_global_options(send, defaults=False)
    send.set_defaults(func=cmd_send)

    add = sub.add_parser("add", help="persist a wake job")
    add_global_options(add, defaults=False)
    add_sub = add.add_subparsers(dest="condition", required=True)
    add_time_condition_parser(add_sub)
    add_goal_condition_parser(add_sub)
    add_cmd_condition_parser(add_sub)
    add.set_defaults(func=cmd_add)

    wait = sub.add_parser("wait", help="block until a condition is ready")
    add_wait_options(wait, defaults=True)
    add_global_options(wait, defaults=False)
    wait_sub = wait.add_subparsers(dest="condition", required=True)
    add_wait_time_condition_parser(wait_sub)
    add_wait_goal_condition_parser(wait_sub)
    add_wait_cmd_condition_parser(wait_sub)
    wait.set_defaults(func=cmd_wait)

    tick = sub.add_parser("tick", help="evaluate pending jobs and fire ready wakes")
    tick.add_argument("--limit", type=parse_positive_int)
    tick.add_argument("--allow-active", action="store_true")
    add_global_options(tick, defaults=False)
    tick.set_defaults(func=cmd_tick)

    list_parser = sub.add_parser("list", help="list wake jobs")
    list_parser.add_argument("--all", action="store_true", help="include fired and canceled jobs")
    add_global_options(list_parser, defaults=False)
    list_parser.set_defaults(func=cmd_list)

    cancel = sub.add_parser("cancel", help="cancel a wake job")
    cancel.add_argument("job_id")
    add_global_options(cancel, defaults=False)
    cancel.set_defaults(func=cmd_cancel)

    return parser


async def dispatch(args: argparse.Namespace) -> int:
    result = args.func(args)
    if asyncio.iscoroutine(result):
        return await result
    return result


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(dispatch(args))
    except BrokenPipeError:
        return 1
    except (OSError, WakectlError, websockets.WebSocketException) as exc:
        print(f"codex-wakectl: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
