from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .errors import LimitctlError


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LimitctlError(f"app-server returned invalid {label}")
    return value


def optional_string(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise LimitctlError(f"app-server returned invalid {label}")
    return value


def optional_int(value: Any, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise LimitctlError(f"app-server returned invalid {label}")
    return value


def normalize_window(
    value: Any,
    *,
    limit_id: str,
    limit_name: str | None,
    plan_type: str | None,
) -> dict[str, Any] | None:
    if value is None:
        return None
    window = require_object(value, f"rate-limit window for {limit_id}")
    used = optional_int(window.get("usedPercent"), "used percentage")
    if used is None or not 0 <= used <= 100:
        raise LimitctlError("app-server returned invalid used percentage")
    duration = optional_int(window.get("windowDurationMins"), "window duration")
    if duration is not None and duration <= 0:
        raise LimitctlError("app-server returned invalid window duration")
    resets_at = optional_int(window.get("resetsAt"), "reset timestamp")
    return {
        "limitId": limit_id,
        "limitName": limit_name,
        "planType": plan_type,
        "windowDurationMins": duration,
        "usedPercent": used,
        "remainingPercent": 100 - used,
        "resetsAt": resets_at,
    }


def snapshot_windows(limit_id: str, value: Any) -> list[dict[str, Any]]:
    snapshot = require_object(value, f"rate-limit snapshot for {limit_id}")
    reported_id = optional_string(snapshot.get("limitId"), "limit id")
    if reported_id is not None and reported_id != limit_id:
        raise LimitctlError(
            f"rate-limit map key {limit_id!r} disagrees with snapshot id {reported_id!r}"
        )
    limit_name = optional_string(snapshot.get("limitName"), "limit name")
    plan_type = optional_string(snapshot.get("planType"), "plan type")

    windows: dict[int | None, dict[str, Any]] = {}
    for label in ("primary", "secondary"):
        normalized = normalize_window(
            snapshot.get(label),
            limit_id=limit_id,
            limit_name=limit_name,
            plan_type=plan_type,
        )
        if normalized is None:
            continue
        duration = normalized["windowDurationMins"]
        previous = windows.get(duration)
        if previous is not None and previous != normalized:
            name = format_duration(duration) if duration is not None else "unknown"
            raise LimitctlError(f"conflicting {name} windows reported for {limit_id}")
        windows[duration] = normalized
    return list(windows.values())


def normalize_rate_limits(value: Any) -> list[dict[str, Any]]:
    result = require_object(value, "account/rateLimits/read result")
    by_id = result.get("rateLimitsByLimitId")
    snapshots: dict[str, Any]
    if isinstance(by_id, dict) and by_id:
        if not all(isinstance(key, str) and key for key in by_id):
            raise LimitctlError("app-server returned invalid rate-limit ids")
        snapshots = by_id
    elif by_id is not None and not isinstance(by_id, dict):
        raise LimitctlError("app-server returned invalid rate-limit map")
    else:
        fallback = require_object(result.get("rateLimits"), "rate-limit snapshot")
        limit_id = optional_string(fallback.get("limitId"), "limit id")
        if not limit_id:
            raise LimitctlError("app-server returned a rate limit without an id")
        snapshots = {limit_id: fallback}

    windows = [
        window
        for limit_id, snapshot in snapshots.items()
        for window in snapshot_windows(limit_id, snapshot)
    ]
    windows.sort(
        key=lambda window: (
            window["limitId"],
            window["windowDurationMins"] is None,
            window["windowDurationMins"] or 0,
        )
    )
    return windows


def select_windows(
    windows: list[dict[str, Any]],
    *,
    limit_id: str | None,
    duration_minutes: int | None,
) -> list[dict[str, Any]]:
    return [
        window
        for window in windows
        if (limit_id is None or window["limitId"] == limit_id)
        and (
            duration_minutes is None
            or window["windowDurationMins"] == duration_minutes
        )
    ]


def format_duration(minutes: int | None) -> str:
    if minutes is None:
        return "unknown"
    remaining = minutes
    parts: list[str] = []
    for suffix, scale in (("d", 1440), ("h", 60), ("m", 1)):
        amount, remaining = divmod(remaining, scale)
        if amount:
            parts.append(f"{amount}{suffix}")
    return "".join(parts)


def format_time(timestamp: int | None) -> str:
    if timestamp is None:
        return "-"
    try:
        return (
            datetime.fromtimestamp(timestamp, timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )
    except (OverflowError, OSError, ValueError) as exc:
        raise LimitctlError("app-server returned invalid reset timestamp") from exc


def format_window(window: dict[str, Any]) -> str:
    name = (
        "-"
        if window["limitName"] is None
        else json.dumps(window["limitName"], ensure_ascii=False, separators=(",", ":"))
    )
    return "\t".join(
        [
            window["limitId"],
            f"name={name}",
            f"window={format_duration(window['windowDurationMins'])}",
            f"used={window['usedPercent']}%",
            f"remaining={window['remainingPercent']}%",
            f"resets={format_time(window['resetsAt'])}",
        ]
    )
