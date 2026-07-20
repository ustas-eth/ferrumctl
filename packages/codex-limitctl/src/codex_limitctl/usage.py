from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .errors import LimitctlError


def normalize_usage(value: Any, since: datetime) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        raise LimitctlError("app-server returned invalid account/usage/read result")
    buckets = value.get("dailyUsageBuckets")
    if buckets is None:
        buckets = []
    if not isinstance(buckets, list):
        raise LimitctlError("app-server returned invalid daily usage buckets")

    days: dict[date, int] = {}
    for bucket in buckets:
        if not isinstance(bucket, dict):
            raise LimitctlError("app-server returned invalid daily usage bucket")
        raw_date = bucket.get("startDate")
        tokens = bucket.get("tokens")
        try:
            parsed_date = date.fromisoformat(raw_date)
        except (TypeError, ValueError) as exc:
            raise LimitctlError("app-server returned invalid daily usage date") from exc
        if isinstance(tokens, bool) or not isinstance(tokens, int) or tokens < 0:
            raise LimitctlError("app-server returned invalid daily token count")
        if parsed_date in days:
            raise LimitctlError("app-server returned duplicate daily usage buckets")
        days[parsed_date] = tokens

    return [
        {"date": day.isoformat(), "tokens": days[day]}
        for day in sorted(days)
        if day >= since.date()
    ]


def format_usage_day(day: dict[str, Any]) -> str:
    return f"{day['date']}\ttokens={day['tokens']}"
