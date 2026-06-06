from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from .appserver import AppServer, appserver_request, connect_appserver
from .errors import GoalctlError


STATUSES = {
    "active",
    "paused",
    "blocked",
    "budgetLimited",
    "usageLimited",
    "complete",
}
MAX_OBJECTIVE_CHARS = 4000


def print_goal(goal: dict[str, Any] | None, as_json: bool) -> int:
    if as_json:
        print(json.dumps({"goal": goal}, indent=2))
        return 0
    if goal is None:
        print("no goal", file=sys.stderr)
        return 1
    print(f"{goal['status']}\t{goal['objective']}")
    return 0


def read_objective(value: str) -> str:
    if value == "-":
        value = sys.stdin.read().rstrip("\n")
    objective = value.strip()
    if not objective:
        raise GoalctlError("objective is empty")
    if len(objective) > MAX_OBJECTIVE_CHARS:
        raise GoalctlError(f"objective is longer than {MAX_OBJECTIVE_CHARS} characters")
    return objective


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def cmd_get(args: argparse.Namespace) -> int:
    result = appserver_request(args, "thread/goal/get", {"threadId": args.thread_id})
    return print_goal(result.get("goal"), args.json)


def set_goal(
    app: AppServer,
    thread_id: str,
    objective: str | None = None,
    status: str | None = None,
    token_budget: int | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"threadId": thread_id}
    if objective is not None:
        params["objective"] = objective
    if status is not None:
        params["status"] = status
    if token_budget is not None:
        params["tokenBudget"] = token_budget
    result = app.request("thread/goal/set", params)
    return result.get("goal")


def cmd_update(args: argparse.Namespace) -> int:
    objective = read_objective(args.objective) if args.objective is not None else None
    if objective is None and args.status is None and args.token_budget is None:
        raise GoalctlError("nothing to update")
    app = connect_appserver(args)
    try:
        goal = set_goal(
            app,
            args.thread_id,
            objective=objective,
            status=args.status,
            token_budget=args.token_budget,
        )
        return print_goal(goal, args.json)
    finally:
        app.close()


def cmd_replace(args: argparse.Namespace) -> int:
    objective = read_objective(args.objective)
    app = connect_appserver(args)
    try:
        app.request("thread/goal/clear", {"threadId": args.thread_id})
        goal = set_goal(
            app,
            args.thread_id,
            objective=objective,
            status=args.status or "active",
            token_budget=args.token_budget,
        )
        return print_goal(goal, args.json)
    finally:
        app.close()


def cmd_clear(args: argparse.Namespace) -> int:
    result = appserver_request(args, "thread/goal/clear", {"threadId": args.thread_id})
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("cleared" if result.get("cleared") else "not cleared")
    return 0


def add_common_options(parser: argparse.ArgumentParser, *, defaults: bool) -> None:
    parser.add_argument(
        "--json",
        action="store_true",
        default=False if defaults else argparse.SUPPRESS,
        help="print JSON output",
    )
    parser.add_argument(
        "--timeout",
        type=positive_float,
        default=(
            float(os.environ.get("CODEX_GOALCTL_TIMEOUT", "20"))
            if defaults
            else argparse.SUPPRESS
        ),
        help="app-server request timeout in seconds",
    )
    parser.add_argument(
        "--codex-bin",
        default=os.environ.get("CODEX_BIN", "codex") if defaults else argparse.SUPPRESS,
        help="codex executable path",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codex-goalctl",
        description="Manage Codex thread goals through codex app-server.",
    )
    add_common_options(parser, defaults=True)

    sub = parser.add_subparsers(dest="command", required=True)

    get = sub.add_parser("get", help="read a thread goal")
    get.add_argument("thread_id")
    add_common_options(get, defaults=False)
    get.set_defaults(func=cmd_get)

    update = sub.add_parser("update", help="update a goal in place")
    update.add_argument("thread_id")
    update.add_argument("objective", nargs="?", help='new goal text, or "-" to read stdin')
    update.add_argument("--status", choices=sorted(STATUSES))
    update.add_argument("--token-budget", type=positive_int)
    add_common_options(update, defaults=False)
    update.set_defaults(func=cmd_update)

    replace = sub.add_parser("replace", help="clear any goal, then create a fresh one")
    replace.add_argument("thread_id")
    replace.add_argument("objective", help='goal text, or "-" to read stdin')
    replace.add_argument("--status", choices=sorted(STATUSES))
    replace.add_argument("--token-budget", type=positive_int)
    add_common_options(replace, defaults=False)
    replace.set_defaults(func=cmd_replace)

    clear = sub.add_parser("clear", help="clear a thread goal")
    clear.add_argument("thread_id")
    add_common_options(clear, defaults=False)
    clear.set_defaults(func=cmd_clear)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except BrokenPipeError:
        return 1
    except GoalctlError as exc:
        print(f"codex-goalctl: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
