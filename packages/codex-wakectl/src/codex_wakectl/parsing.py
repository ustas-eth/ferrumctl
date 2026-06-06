from __future__ import annotations

import argparse
import re
import time
from datetime import datetime

from .constants import STATUS_VALUES


DURATION_RE = re.compile(r"^([0-9][0-9_]*)([smhd])$")


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


def parse_positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive number") from exc
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
