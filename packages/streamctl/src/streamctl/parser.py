from __future__ import annotations

import argparse
from pathlib import Path

from .commands import cmd_ack, cmd_append, cmd_create, cmd_list
from .constants import CLIENT_VERSION
from .state import default_state_path


def nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def nonempty_text(value: str) -> str:
    if not value.strip():
        raise argparse.ArgumentTypeError("must not be empty")
    return value


def add_global_options(parser: argparse.ArgumentParser, *, defaults: bool) -> None:
    parser.add_argument(
        "--state",
        type=Path,
        default=default_state_path() if defaults else argparse.SUPPRESS,
        help="stream state database",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False if defaults else argparse.SUPPRESS,
        help="print JSON output",
    )


def add_identity_option(
    parser: argparse.ArgumentParser,
    option: str,
    *,
    dest: str,
) -> None:
    parser.add_argument(
        option,
        dest=dest,
        type=nonempty_text,
        help=f"{dest} identity (default: CODEX_THREAD_ID)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="streamctl",
        description="Share durable append-only streams between coding agents.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {CLIENT_VERSION}",
    )
    add_global_options(parser, defaults=True)
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="create a stream")
    create.add_argument("--label", type=nonempty_text, help="optional display label")
    add_global_options(create, defaults=False)
    create.set_defaults(func=cmd_create)

    append = sub.add_parser("append", help="append an immutable entry")
    append.add_argument("stream_id", help="stream to append to")
    add_identity_option(append, "--author", dest="author")
    append.add_argument("--reply-to", type=positive_int, help="position being answered")
    append.add_argument("message", type=nonempty_text, help="entry text")
    add_global_options(append, defaults=False)
    append.set_defaults(func=cmd_append)

    list_parser = sub.add_parser("list", help="list entries in stream order")
    list_parser.add_argument("stream_id", help="stream to read")
    list_parser.add_argument(
        "--reader",
        dest="reader",
        type=nonempty_text,
        help=(
            "reader identity "
            "(default: CODEX_THREAD_ID unless --after is specified)"
        ),
    )
    list_parser.add_argument(
        "--after",
        type=nonnegative_int,
        help="exclusive position; overrides the reader acknowledgement",
    )
    list_parser.add_argument(
        "--limit",
        type=nonnegative_int,
        default=20,
        help="entries to return; 0 reads the full selected interval",
    )
    add_global_options(list_parser, defaults=False)
    list_parser.set_defaults(func=cmd_list)

    ack = sub.add_parser("ack", help="advance a reader acknowledgement")
    ack.add_argument("stream_id", help="stream being acknowledged")
    add_identity_option(ack, "--reader", dest="reader")
    ack.add_argument(
        "--through",
        type=nonnegative_int,
        required=True,
        help="last fully processed position",
    )
    add_global_options(ack, defaults=False)
    ack.set_defaults(func=cmd_ack)

    return parser
