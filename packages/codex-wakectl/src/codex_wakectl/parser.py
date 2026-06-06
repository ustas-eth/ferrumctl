from __future__ import annotations

import argparse
from pathlib import Path

from .commands import (
    cmd_add,
    cmd_cancel,
    cmd_list,
    cmd_loaded,
    cmd_run,
    cmd_send,
    cmd_status,
    cmd_systemd_install,
    cmd_systemd_uninstall,
    cmd_wait,
)
from .conditions import (
    build_cmd_condition,
    build_goal_condition,
    build_stop_condition,
    build_time_condition,
)
from .constants import DEFAULT_LEASE_SECONDS, DEFAULT_SYSTEMD_INTERVAL_SECONDS, DEFAULT_TIMEOUT
from .parsing import parse_at, parse_duration, parse_positive_float, parse_positive_int, parse_statuses
from .state import default_state_path


def add_global_options(parser: argparse.ArgumentParser, *, defaults: bool) -> None:
    parser.add_argument(
        "--endpoint",
        default="unix://" if defaults else argparse.SUPPRESS,
        help="app-server endpoint: unix://, unix://PATH, or ws://HOST:PORT",
    )
    parser.add_argument(
        "--timeout",
        type=parse_positive_float,
        default=DEFAULT_TIMEOUT if defaults else argparse.SUPPRESS,
        help="app-server request and command predicate timeout in seconds",
    )
    parser.add_argument(
        "--state",
        type=Path,
        default=default_state_path() if defaults else argparse.SUPPRESS,
        help="wake job state database",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False if defaults else argparse.SUPPRESS,
        help="print JSON output",
    )


def add_state_json_options(parser: argparse.ArgumentParser, *, defaults: bool) -> None:
    parser.add_argument(
        "--state",
        type=Path,
        default=default_state_path() if defaults else argparse.SUPPRESS,
        help="wake job state database",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False if defaults else argparse.SUPPRESS,
        help="print JSON output",
    )


def add_json_option(parser: argparse.ArgumentParser, *, defaults: bool) -> None:
    parser.add_argument(
        "--json",
        action="store_true",
        default=False if defaults else argparse.SUPPRESS,
        help="print JSON output",
    )


def add_target_message(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--to", dest="to_thread_id", required=True, help="thread to wake")
    parser.add_argument(
        "--allow-active",
        action="store_true",
        help="allow this queued wake to start while the target thread is active",
    )
    parser.add_argument("message", help="message to send when the wake fires")


def add_time_condition_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser("time", help="time-based condition")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--after", type=parse_duration, help="duration such as 10m or 2h")
    group.add_argument("--at", type=parse_at, help="ISO timestamp with timezone")
    parser.set_defaults(condition_builder=build_time_condition)
    add_target_message(parser)
    add_global_options(parser, defaults=False)


def add_goal_condition_options(
    parser: argparse.ArgumentParser,
    *,
    allow_max_fires: bool,
) -> None:
    parser.add_argument("thread_id", help="goal thread to watch")
    parser.add_argument("--status", type=parse_statuses, help="comma-separated goal statuses")
    parser.add_argument("--tokens-left-lte", type=parse_positive_int)
    parser.add_argument("--tokens-used-gte", type=parse_positive_int)
    parser.add_argument("--tokens-used-every", type=parse_positive_int)
    parser.add_argument("--time-used-gte", type=parse_duration)
    parser.add_argument("--time-used-every", type=parse_duration)
    if allow_max_fires:
        parser.add_argument(
            "--max-fires",
            type=parse_positive_int,
            help="maximum fires for a repeating goal predicate",
        )
    parser.set_defaults(condition_builder=build_goal_condition)


def add_goal_condition_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser("goal", help="goal-state condition")
    add_goal_condition_options(parser, allow_max_fires=True)
    add_target_message(parser)
    add_global_options(parser, defaults=False)


def add_cmd_condition_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser("cmd", help="shell command predicate")
    add_target_message(parser)
    parser.add_argument("argv", nargs=argparse.REMAINDER, help="command after --")
    parser.set_defaults(condition_builder=build_cmd_condition)
    add_global_options(parser, defaults=False)


def add_stop_condition_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser("stop", help="thread stop edge condition")
    parser.add_argument("thread_id", help="thread to watch")
    parser.add_argument(
        "--repeat",
        action="store_true",
        help="re-arm after each stop and fire again after the next active-to-idle edge",
    )
    parser.add_argument(
        "--max-fires",
        type=parse_positive_int,
        help="maximum fires for --repeat",
    )
    parser.set_defaults(condition_builder=build_stop_condition)
    add_target_message(parser)
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
    add_goal_condition_options(parser, allow_max_fires=False)
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


def add_wait_stop_condition_parser(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = sub.add_parser("stop", help="wait for thread stop edge")
    parser.add_argument("thread_id", help="thread to watch")
    parser.set_defaults(condition_builder=build_stop_condition)
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
    add_stop_condition_parser(add_sub)
    add.set_defaults(func=cmd_add)

    wait = sub.add_parser("wait", help="block until a condition is ready")
    add_wait_options(wait, defaults=True)
    add_global_options(wait, defaults=False)
    wait_sub = wait.add_subparsers(dest="condition", required=True)
    add_wait_time_condition_parser(wait_sub)
    add_wait_goal_condition_parser(wait_sub)
    add_wait_cmd_condition_parser(wait_sub)
    add_wait_stop_condition_parser(wait_sub)
    wait.set_defaults(func=cmd_wait)

    run = sub.add_parser("run", help="evaluate pending jobs once and fire ready wakes")
    run.add_argument("--limit", type=parse_positive_int)
    run.add_argument(
        "--lease-seconds",
        type=parse_positive_int,
        default=DEFAULT_LEASE_SECONDS,
        help="seconds before a claimed job can be reclaimed",
    )
    add_global_options(run, defaults=False)
    run.set_defaults(func=cmd_run)

    list_parser = sub.add_parser("list", help="list wake jobs")
    list_parser.add_argument("--all", action="store_true", help="include fired and canceled jobs")
    add_global_options(list_parser, defaults=False)
    list_parser.set_defaults(func=cmd_list)

    cancel = sub.add_parser("cancel", help="cancel a wake job")
    cancel.add_argument("job_id")
    add_global_options(cancel, defaults=False)
    cancel.set_defaults(func=cmd_cancel)

    systemd = sub.add_parser("systemd", help="install or remove user systemd units")
    systemd_sub = systemd.add_subparsers(dest="systemd_command", required=True)

    systemd_install = systemd_sub.add_parser("install", help="install and start user timer")
    systemd_install.add_argument(
        "--interval",
        type=parse_duration,
        default=DEFAULT_SYSTEMD_INTERVAL_SECONDS,
        help="timer interval such as 30s or 5m",
    )
    add_state_json_options(systemd_install, defaults=False)
    systemd_install.set_defaults(func=cmd_systemd_install)

    systemd_uninstall = systemd_sub.add_parser("uninstall", help="stop and remove user timer")
    add_json_option(systemd_uninstall, defaults=False)
    systemd_uninstall.set_defaults(func=cmd_systemd_uninstall)

    return parser
