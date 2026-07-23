from __future__ import annotations

import argparse
import math

from .commands import (
    cmd_inspect,
    cmd_interrupt,
    cmd_items,
    cmd_list,
    cmd_loaded,
    cmd_message,
    cmd_messages,
    cmd_resume,
    cmd_search,
    cmd_start,
    cmd_status,
    cmd_steer,
    cmd_terminals,
    cmd_terminate_terminal,
)
from .constants import CLIENT_VERSION, DEFAULT_TIMEOUT


def positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive finite number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive finite number")
    return parsed


def nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def nonempty_text(value: str) -> str:
    if not value.strip():
        raise argparse.ArgumentTypeError("must not be empty")
    return value


def add_global_options(parser: argparse.ArgumentParser, *, defaults: bool) -> None:
    parser.add_argument(
        "--endpoint",
        default="unix://" if defaults else argparse.SUPPRESS,
        help="app-server endpoint: unix://, unix://PATH, ws://HOST:PORT, or wss://HOST:PORT",
    )
    parser.add_argument(
        "--timeout",
        type=positive_float,
        default=DEFAULT_TIMEOUT if defaults else argparse.SUPPRESS,
        help="app-server request timeout in seconds",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False if defaults else argparse.SUPPRESS,
        help="print JSON output",
    )


def add_item_range_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--turn",
        metavar="TURN_ID",
        help="restrict results to one turn",
    )
    parser.add_argument(
        "--after",
        nargs=2,
        metavar=("TURN_ID", "ITEM_ID"),
        help="start after this item",
    )
    parser.add_argument(
        "--before",
        nargs=2,
        metavar=("TURN_ID", "ITEM_ID"),
        help="stop before this item",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codex-threadctl",
        description="Inspect and control app-server-backed Codex threads.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {CLIENT_VERSION}"
    )
    add_global_options(parser, defaults=True)
    sub = parser.add_subparsers(dest="command", required=True)

    loaded = sub.add_parser("loaded", help="list loaded thread ids")
    add_global_options(loaded, defaults=False)
    loaded.set_defaults(func=cmd_loaded)

    list_parser = sub.add_parser("list", help="list persisted threads")
    relation = list_parser.add_mutually_exclusive_group()
    relation.add_argument(
        "--parent",
        metavar="THREAD_ID",
        help="list threads spawned directly by this thread",
    )
    relation.add_argument(
        "--ancestor",
        metavar="THREAD_ID",
        help="list spawned descendants at any depth",
    )
    list_parser.add_argument(
        "--limit",
        type=nonnegative_int,
        default=20,
        help="threads to return; 0 reads all matching threads",
    )
    list_parser.add_argument(
        "--sort",
        choices=("created", "recency", "updated"),
        default="recency",
        help="newest-first ordering (default: recency)",
    )
    add_global_options(list_parser, defaults=False)
    list_parser.set_defaults(func=cmd_list)

    search = sub.add_parser("search", help="search persisted thread content")
    search.add_argument("search_term", type=nonempty_text)
    search.add_argument(
        "--limit",
        type=nonnegative_int,
        default=20,
        help="threads to return; 0 reads all matching threads",
    )
    search.add_argument(
        "--sort",
        choices=("created", "recency", "updated"),
        default="recency",
        help="newest-first ordering (default: recency)",
    )
    add_global_options(search, defaults=False)
    search.set_defaults(func=cmd_search)

    status = sub.add_parser("status", help="show loaded state and thread status")
    status.add_argument("thread_id")
    add_global_options(status, defaults=False)
    status.set_defaults(func=cmd_status)

    inspect = sub.add_parser("inspect", help="show current state and recent activity")
    inspect.add_argument("thread_id")
    inspect.add_argument(
        "--items",
        type=nonnegative_int,
        default=12,
        help="recent latest-turn items to print; 0 prints all",
    )
    inspect.add_argument(
        "--brief",
        action="store_true",
        help="load only turn summaries, without command or tool activity",
    )
    inspect.add_argument(
        "--no-previous",
        action="store_true",
        help="omit the previous turn and its response",
    )
    add_global_options(inspect, defaults=False)
    inspect.set_defaults(func=cmd_inspect)

    messages = sub.add_parser("messages", help="list recent conversation messages")
    messages.add_argument("thread_id")
    messages.add_argument(
        "--limit",
        type=nonnegative_int,
        default=20,
        help="messages to return; 0 scans the selected materialized history",
    )
    add_item_range_options(messages)
    add_global_options(messages, defaults=False)
    messages.set_defaults(func=cmd_messages)

    items = sub.add_parser(
        "items",
        help="list compact materialized activity summaries",
    )
    items.add_argument("thread_id")
    items.add_argument(
        "--type",
        dest="types",
        action="append",
        default=[],
        metavar="TYPE",
        help="include this item type; repeat to include more",
    )
    items.add_argument(
        "--limit",
        type=nonnegative_int,
        default=20,
        help="items to return; 0 scans the selected materialized history",
    )
    add_item_range_options(items)
    add_global_options(items, defaults=False)
    items.set_defaults(func=cmd_items)

    message = sub.add_parser(
        "message",
        help="print the retained text of one conversation message",
    )
    message.add_argument("thread_id")
    message.add_argument("turn_id")
    message.add_argument("item_id")
    add_global_options(message, defaults=False)
    message.set_defaults(func=cmd_message)

    start = sub.add_parser("start", help="send input as a new turn on an idle thread")
    start.add_argument("thread_id")
    start.add_argument("message")
    add_global_options(start, defaults=False)
    start.set_defaults(func=cmd_start)

    steer = sub.add_parser("steer", help="send input to one expected active turn")
    steer.add_argument("thread_id")
    steer.add_argument("turn_id")
    steer.add_argument("message")
    add_global_options(steer, defaults=False)
    steer.set_defaults(func=cmd_steer)

    interrupt = sub.add_parser("interrupt", help="request interruption of one turn")
    interrupt.add_argument("thread_id")
    interrupt.add_argument("turn_id")
    interrupt.add_argument(
        "--wait",
        action="store_true",
        help="wait for the turn to reach a terminal status",
    )
    add_global_options(interrupt, defaults=False)
    interrupt.set_defaults(func=cmd_interrupt)

    terminals = sub.add_parser(
        "terminals",
        help="list running terminal processes for a loaded thread",
    )
    terminals.add_argument("thread_id")
    terminals.add_argument(
        "--limit",
        type=nonnegative_int,
        default=20,
        help="terminals to return; 0 reads all",
    )
    add_global_options(terminals, defaults=False)
    terminals.set_defaults(func=cmd_terminals)

    terminate_terminal = sub.add_parser(
        "terminate-terminal",
        help="terminate one running terminal by process id",
    )
    terminate_terminal.add_argument("thread_id")
    terminate_terminal.add_argument("process_id")
    terminate_terminal.add_argument(
        "--item",
        dest="item_id",
        required=True,
        help="expected item id from the current terminals listing",
    )
    add_global_options(terminate_terminal, defaults=False)
    terminate_terminal.set_defaults(func=cmd_terminate_terminal)

    resume = sub.add_parser("resume", help="load a persisted thread on app-server")
    resume.add_argument("thread_id")
    resume.add_argument(
        "--continue-goal",
        action="store_true",
        required=True,
        help="acknowledge that resume can continue an active goal",
    )
    add_global_options(resume, defaults=False)
    resume.set_defaults(func=cmd_resume)

    return parser
