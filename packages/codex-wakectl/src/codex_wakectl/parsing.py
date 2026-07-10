from __future__ import annotations

import argparse
import math
import re
import time
from datetime import datetime

from .constants import STATUS_VALUES


INTEGER_RE = r"(?:0|[1-9][0-9]*(?:_[0-9]+)*)"
DURATION_RE = re.compile(
    rf"^(?:(?P<d>{INTEGER_RE})d)?"
    rf"(?:(?P<h>{INTEGER_RE})h)?"
    rf"(?:(?P<m>{INTEGER_RE})m)?"
    rf"(?:(?P<s>{INTEGER_RE})s)?$"
)


def now_seconds() -> int:
    return int(time.time())


def parse_duration(value: str) -> int:
    match = DURATION_RE.fullmatch(value)
    if match is None:
        raise argparse.ArgumentTypeError(
            "must be a positive duration with unique descending units, such as 3m30s"
        )
    seconds = sum(
        int(match.group(unit).replace("_", "")) * scale
        for unit, scale in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1))
        if match.group(unit) is not None
    )
    if seconds <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return seconds


def parse_positive_int(value: str) -> int:
    try:
        parsed = int(value.replace("_", ""))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def parse_positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
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
