from __future__ import annotations

import argparse
import json
import os
import selectors
import subprocess
import sys
import time
from typing import Any


STATUSES = {
    "active",
    "paused",
    "blocked",
    "budgetLimited",
    "usageLimited",
    "complete",
}
MAX_OBJECTIVE_CHARS = 4000


class GoalctlError(RuntimeError):
    pass


class AppServer:
    def __init__(self, codex_bin: str, timeout: float):
        self.timeout = timeout
        try:
            self.proc = subprocess.Popen(
                [codex_bin, "app-server", "--listen", "stdio://"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            raise GoalctlError(f"failed to start {codex_bin!r}: {exc}") from exc
        self.sel = selectors.DefaultSelector()
        self.sel.register(self.proc.stdout, selectors.EVENT_READ, "stdout")
        self.sel.register(self.proc.stderr, selectors.EVENT_READ, "stderr")
        self.stderr_tail: list[str] = []
        self.next_id = 1

    def close(self) -> None:
        if self.proc.poll() is not None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=2)

    def send(self, msg: dict[str, Any]) -> None:
        if self.proc.stdin is None:
            raise GoalctlError("app-server stdin is unavailable")
        self.proc.stdin.write(json.dumps(msg, separators=(",", ":")) + "\n")
        self.proc.stdin.flush()

    def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        request_id = self.next_id
        self.next_id += 1
        msg: dict[str, Any] = {"method": method, "id": request_id}
        if params is not None:
            msg["params"] = params
        self.send(msg)
        return self.wait_for(request_id)

    def notify(self, method: str) -> None:
        self.send({"method": method})

    def wait_for(self, request_id: int) -> Any:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise GoalctlError(self.format_error("app-server exited"))
            for key, _ in self.sel.select(timeout=0.2):
                line = key.fileobj.readline()
                if not line:
                    continue
                if key.data == "stderr":
                    self.stderr_tail.append(line.rstrip())
                    self.stderr_tail = self.stderr_tail[-20:]
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise GoalctlError(f"invalid app-server JSON: {line.rstrip()}") from exc
                if msg.get("id") != request_id:
                    continue
                if "error" in msg:
                    raise GoalctlError(json.dumps(msg["error"], separators=(",", ":")))
                return msg.get("result")
        raise GoalctlError(self.format_error("timed out waiting for app-server"))

    def format_error(self, message: str) -> str:
        if not self.stderr_tail:
            return message
        return message + "\n" + "\n".join(self.stderr_tail)


def appserver_request(args: argparse.Namespace, method: str, params: dict[str, Any]) -> Any:
    app = connect_appserver(args)
    try:
        return app.request(method, params)
    finally:
        app.close()


def connect_appserver(args: argparse.Namespace) -> AppServer:
    app = AppServer(args.codex_bin, args.timeout)
    try:
        app.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "codex_goalctl",
                    "title": "codex-goalctl",
                    "version": "0.1.0",
                }
            },
        )
        app.notify("initialized")
        return app
    except Exception:
        app.close()
        raise


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
