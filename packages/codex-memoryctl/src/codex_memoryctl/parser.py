from __future__ import annotations

import argparse
import math

from .commands import cmd_export, cmd_inject, cmd_list, cmd_show
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
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be zero or greater") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def nonempty(value: str) -> str:
    if not value.strip():
        raise argparse.ArgumentTypeError("must not be empty")
    return value


def add_global_options(parser: argparse.ArgumentParser, *, defaults: bool) -> None:
    parser.add_argument(
        "--codex-home",
        default=None if defaults else argparse.SUPPRESS,
        help="Codex home containing sessions and archived_sessions",
    )
    parser.add_argument(
        "--endpoint",
        default="unix://" if defaults else argparse.SUPPRESS,
        help="app-server endpoint used for task names and injection",
    )
    parser.add_argument(
        "--timeout",
        type=positive_float,
        default=DEFAULT_TIMEOUT if defaults else argparse.SUPPRESS,
        help="app-server request timeout in seconds",
    )
    parser.add_argument(
        "--tree",
        default=None if defaults else argparse.SUPPRESS,
        metavar="THREAD_ID",
        help="thread id that scopes canonical task-name resolution",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False if defaults else argparse.SUPPRESS,
        help="print JSON output",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codex-memoryctl",
        description="Inspect, export, and inject Codex compaction memory.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {CLIENT_VERSION}"
    )
    add_global_options(parser, defaults=True)
    sub = parser.add_subparsers(dest="command", required=True)

    list_parser = sub.add_parser(
        "list", help="list memory checkpoints and standalone memory sightings"
    )
    list_parser.add_argument(
        "source",
        nargs="?",
        help="thread id, task name, or rollout path (default: CODEX_THREAD_ID)",
    )
    list_parser.add_argument(
        "--origin",
        choices=("all", "checkpoint", "standalone"),
        default="all",
        help="restrict observations by origin",
    )
    list_parser.add_argument(
        "--limit",
        type=nonnegative_int,
        default=20,
        help="newest observations to print; 0 prints all",
    )
    add_global_options(list_parser, defaults=False)
    list_parser.set_defaults(func=cmd_list)

    show = sub.add_parser("show", help="show one memory observation without its blob")
    show.add_argument("state", help="SOURCE@SELECTOR memory reference")
    add_global_options(show, defaults=False)
    show.set_defaults(func=cmd_show)

    export = sub.add_parser("export", help="write a portable memory export")
    export.add_argument("state", help="SOURCE@SELECTOR memory reference")
    export.add_argument(
        "--output",
        "-o",
        required=True,
        help="new output file, or - for explicit stdout",
    )
    export.add_argument(
        "--full-checkpoint",
        action="store_true",
        help="include the checkpoint's retained history instead of memory only",
    )
    export.add_argument(
        "--force",
        action="store_true",
        help="replace an existing output file",
    )
    add_global_options(export, defaults=False)
    export.set_defaults(func=cmd_export)

    inject = sub.add_parser(
        "inject", help="append compaction memory to one loaded Codex thread"
    )
    inject.add_argument(
        "target",
        nargs="?",
        help="target thread id or task name (default: CODEX_THREAD_ID)",
    )
    source = inject.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--state",
        action="append",
        type=nonempty,
        help="SOURCE@SELECTOR; repeat for one ordered memory-only batch",
    )
    source.add_argument("--file", help="portable memory export, or - for stdin")
    inject.add_argument(
        "--full-checkpoint",
        action="store_true",
        help="inject one source checkpoint including its retained history",
    )
    inject.add_argument(
        "--purpose",
        type=nonempty,
        help="record the caller's reason in command output",
    )
    inject.add_argument(
        "--allow-duplicate",
        action="store_true",
        help="inject memory already observed in the target rollout",
    )
    inject.add_argument(
        "--allow-non-openai",
        action="store_true",
        help="attempt injection when the target provider is not OpenAI",
    )
    add_global_options(inject, defaults=False)
    inject.set_defaults(func=cmd_inject)

    return parser
