from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from typing import Any

from . import __version__
from .appserver import read_rate_limits
from .errors import LimitctlError
from .limits import (
    format_duration,
    format_window,
    normalize_rate_limits,
    select_windows,
)


DURATION_RE = re.compile(
    r"^(?:(?P<d>[0-9]+)d)?(?:(?P<h>[0-9]+)h)?(?:(?P<m>[0-9]+)m)?(?:(?P<s>[0-9]+)s)?$"
)


def positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def percentage(value: str) -> int:
    raw = value.removesuffix("%")
    try:
        parsed = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer percentage") from exc
    if not 0 <= parsed <= 100:
        raise argparse.ArgumentTypeError("must be between 0 and 100")
    return parsed


def window_duration(value: str) -> int:
    match = DURATION_RE.fullmatch(value)
    if match is None:
        raise argparse.ArgumentTypeError(
            "must use descending duration units, such as 5h or 1d12h"
        )
    seconds = sum(
        int(match.group(unit)) * scale
        for unit, scale in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1))
        if match.group(unit) is not None
    )
    if seconds <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    if seconds % 60:
        raise argparse.ArgumentTypeError("must resolve to whole minutes")
    return seconds // 60


def load_windows(args: argparse.Namespace) -> list[dict[str, Any]]:
    return normalize_rate_limits(read_rate_limits(args.codex_bin, args.timeout))


def no_match_message(limit_id: str | None, duration: int | None) -> str:
    if limit_id is not None and duration is not None:
        return f"{limit_id} has no reported {format_duration(duration)} window"
    if limit_id is not None:
        return f"no rate-limit windows reported for {limit_id}"
    if duration is not None:
        return f"no {format_duration(duration)} rate-limit windows reported"
    return "no rate-limit windows reported"


def cmd_list(args: argparse.Namespace) -> int:
    selected = select_windows(
        load_windows(args),
        limit_id=args.limit_id,
        duration_minutes=args.window,
    )
    if not selected:
        raise LimitctlError(no_match_message(args.limit_id, args.window))
    if args.json:
        print(json.dumps({"windows": selected}, indent=2))
    else:
        for window in selected:
            print(format_window(window))
    return 0


def cmd_test(args: argparse.Namespace) -> int:
    selected = select_windows(
        load_windows(args),
        limit_id=args.limit_id,
        duration_minutes=args.window,
    )
    if not selected:
        raise LimitctlError(no_match_message(args.limit_id, args.window))
    if len(selected) != 1:
        raise LimitctlError("test predicate matched more than one rate-limit window")
    window = selected[0]
    if args.remaining_at_least is not None:
        matched = window["remainingPercent"] >= args.remaining_at_least
        predicate = {"remainingAtLeast": args.remaining_at_least}
    else:
        matched = window["remainingPercent"] <= args.remaining_at_most
        predicate = {"remainingAtMost": args.remaining_at_most}
    if args.json:
        print(
            json.dumps(
                {"matched": matched, "window": window, "predicate": predicate},
                indent=2,
            )
        )
    return 0 if matched else 1


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
            os.environ.get("CODEX_LIMITCTL_TIMEOUT", "20")
            if defaults
            else argparse.SUPPRESS
        ),
        help="account observation timeout in seconds",
    )
    parser.add_argument(
        "--codex-bin",
        default=os.environ.get("CODEX_BIN", "codex") if defaults else argparse.SUPPRESS,
        help="codex executable path",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codex-limitctl",
        description="Inspect Codex subscription rate-limit windows.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    add_common_options(parser, defaults=True)
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list", help="list reported rate-limit windows")
    listing.add_argument("limit_id", nargs="?", help="optional backend limit id")
    listing.add_argument(
        "--window",
        type=window_duration,
        help="exact window duration, such as 5h or 7d",
    )
    add_common_options(listing, defaults=False)
    listing.set_defaults(func=cmd_list)

    test = sub.add_parser("test", help="test remaining capacity")
    test.add_argument("limit_id", help="backend limit id")
    test.add_argument(
        "--window",
        type=window_duration,
        required=True,
        help="exact window duration, such as 5h or 7d",
    )
    predicate = test.add_mutually_exclusive_group(required=True)
    predicate.add_argument(
        "--remaining-at-least",
        type=percentage,
        help="succeed when remaining percentage is at least this value",
    )
    predicate.add_argument(
        "--remaining-at-most",
        type=percentage,
        help="succeed when remaining percentage is at most this value",
    )
    add_common_options(test, defaults=False)
    test.set_defaults(func=cmd_test)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except BrokenPipeError:
        return 1
    except LimitctlError as exc:
        print(f"codex-limitctl: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
