from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from .errors import LimitctlError


DURATION_RE = re.compile(
    r"^(?:(?P<d>[0-9]+)d)?(?:(?P<h>[0-9]+)h)?(?:(?P<m>[0-9]+)m)?(?:(?P<s>[0-9]+)s)?$"
)


def duration_seconds(value: str) -> int:
    match = DURATION_RE.fullmatch(value)
    if match is None:
        raise ValueError("invalid duration")
    seconds = sum(
        int(match.group(unit)) * scale
        for unit, scale in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1))
        if match.group(unit) is not None
    )
    if seconds <= 0:
        raise ValueError("invalid duration")
    return seconds


def parse_since(value: str, now: datetime | None = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    try:
        return current - timedelta(seconds=duration_seconds(value))
    except (OverflowError, ValueError):
        pass

    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise LimitctlError(
            "--since must be a duration, UTC date, or RFC3339 timestamp"
        ) from exc
    if parsed.tzinfo is None:
        if "T" in value or " " in value:
            raise LimitctlError("--since timestamp must include a UTC offset")
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )
