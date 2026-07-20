from __future__ import annotations

import json
import math
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .errors import LimitctlError
from .limits import format_duration
from .timeparse import format_timestamp


TOKEN_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)
THREAD_ID_RE = re.compile(
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$"
)
INTERESTING_MARKERS = (
    '"session_meta"',
    '"turn_context"',
    '"thread_settings_applied"',
    '"token_count"',
)
RESET_TOLERANCE_SECONDS = 120


def resolve_codex_home(value: str | None) -> Path:
    if value:
        home = Path(value).expanduser()
    elif os.environ.get("CODEX_HOME"):
        home = Path(os.environ["CODEX_HOME"]).expanduser()
    else:
        home = Path.home() / ".codex"
    if not home.is_dir():
        raise LimitctlError(f"Codex home is not a directory: {home}")
    return home


def find_rollouts(codex_home: Path, since: datetime) -> list[Path]:
    cutoff = since.timestamp()
    by_thread: dict[str, tuple[Path, float]] = {}
    for directory in (codex_home / "sessions", codex_home / "archived_sessions"):
        if not directory.is_dir():
            continue
        try:
            candidates = directory.rglob("rollout-*.jsonl")
            for path in candidates:
                try:
                    stat = path.stat()
                except FileNotFoundError:
                    continue
                if stat.st_mtime < cutoff:
                    continue
                match = THREAD_ID_RE.search(path.name)
                key = match.group(1) if match else str(path.resolve())
                previous = by_thread.get(key)
                if previous is None or stat.st_mtime > previous[1]:
                    by_thread[key] = (path, stat.st_mtime)
        except OSError as exc:
            raise LimitctlError(
                f"failed to scan rollout directory {directory}: {exc}"
            ) from exc
    return sorted(path for path, _ in by_thread.values())


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def parse_token_counter(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    result: dict[str, int] = {}
    for field in TOKEN_FIELDS:
        item = value.get(field)
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            return None
        result[field] = item
    return result


def token_delta(
    total: dict[str, int],
    last: dict[str, int] | None,
    previous: dict[str, int] | None,
) -> tuple[dict[str, int] | None, dict[str, int]]:
    if previous is None:
        delta = total if last == total else None
        return delta, total
    if any(total[field] < previous[field] for field in TOKEN_FIELDS):
        return None, total
    delta = {field: total[field] - previous[field] for field in TOKEN_FIELDS}
    return (delta if delta["total_tokens"] > 0 else None), total


def normalize_window_minutes(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    if 295 <= value <= 305:
        return 300
    if 10070 <= value <= 10090:
        return 10080
    return value


def normalize_used_percent(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or not 0 <= value <= 100:
        return None
    return int(value) if float(value).is_integer() else value


def history_rows(
    rate_limits: Any,
    *,
    observed_at: datetime,
    thread_id: str,
    model: str,
    service_tier: str,
) -> Iterable[dict[str, Any]]:
    if not isinstance(rate_limits, dict):
        return
    limit_id = rate_limits.get("limit_id")
    if not isinstance(limit_id, str) or not limit_id:
        return
    for position in ("primary", "secondary"):
        window = rate_limits.get(position)
        if not isinstance(window, dict):
            continue
        duration = normalize_window_minutes(window.get("window_minutes"))
        used = normalize_used_percent(window.get("used_percent"))
        resets_at = window.get("resets_at")
        if duration is None or used is None:
            continue
        if resets_at is not None:
            if (
                isinstance(resets_at, bool)
                or not isinstance(resets_at, int)
                or resets_at <= 0
            ):
                continue
            try:
                datetime.fromtimestamp(resets_at, timezone.utc)
            except (OverflowError, OSError, ValueError):
                continue
        yield {
            "observedAt": format_timestamp(observed_at),
            "threadId": thread_id,
            "model": model,
            "serviceTier": service_tier,
            "limitId": limit_id,
            "windowDurationMins": duration,
            "usedPercent": used,
            "remainingPercent": 100 - used,
            "resetsAt": resets_at,
        }


def read_rollout(
    path: Path,
    since: datetime,
) -> tuple[list[tuple[datetime, dict[str, Any]]], dict[tuple[str, ...], dict[str, int]]]:
    match = THREAD_ID_RE.search(path.name)
    thread_id = match.group(1) if match else path.stem
    model = "unknown"
    service_tier = "default"
    previous_total: dict[str, int] | None = None
    prior_history: dict[tuple[str, int], tuple[int | float, int | None]] = {}
    history: list[tuple[datetime, dict[str, Any]]] = []
    activity: dict[tuple[str, ...], dict[str, int]] = defaultdict(
        lambda: {"updates": 0, **{field: 0 for field in TOKEN_FIELDS}}
    )

    try:
        with path.open("r", encoding="utf-8", errors="replace") as rollout:
            for line in rollout:
                if not any(marker in line for marker in INTERESTING_MARKERS):
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                record_type = record.get("type")
                payload = record.get("payload")
                if not isinstance(payload, dict):
                    continue

                if record_type == "session_meta":
                    reported_id = payload.get("id")
                    if isinstance(reported_id, str) and reported_id:
                        thread_id = reported_id
                    continue
                if record_type == "turn_context":
                    reported_model = payload.get("model")
                    reported_tier = payload.get("service_tier")
                    if isinstance(reported_model, str) and reported_model:
                        model = reported_model
                    if isinstance(reported_tier, str) and reported_tier:
                        service_tier = reported_tier
                    elif "service_tier" in payload and reported_tier is None:
                        service_tier = "default"
                    continue
                if record_type != "event_msg":
                    continue
                if payload.get("type") == "thread_settings_applied":
                    settings = payload.get("thread_settings")
                    if isinstance(settings, dict):
                        reported_model = settings.get("model")
                        reported_tier = settings.get("service_tier")
                        if isinstance(reported_model, str) and reported_model:
                            model = reported_model
                        if isinstance(reported_tier, str) and reported_tier:
                            service_tier = reported_tier
                        elif "service_tier" in settings and reported_tier is None:
                            service_tier = "default"
                    continue
                if payload.get("type") != "token_count":
                    continue

                observed_at = parse_timestamp(record.get("timestamp"))
                info = payload.get("info")
                if isinstance(info, dict):
                    total = parse_token_counter(info.get("total_token_usage"))
                    last = parse_token_counter(info.get("last_token_usage"))
                else:
                    total = None
                    last = None
                if total is not None:
                    delta, previous_total = token_delta(total, last, previous_total)
                else:
                    delta = None

                if observed_at is None or observed_at < since:
                    continue
                rate_limits = payload.get("rate_limits")
                for row in history_rows(
                    rate_limits,
                    observed_at=observed_at,
                    thread_id=thread_id,
                    model=model,
                    service_tier=service_tier,
                ):
                    history_key = (row["limitId"], row["windowDurationMins"])
                    state = (row["usedPercent"], row["resetsAt"])
                    if prior_history.get(history_key) != state:
                        prior_history[history_key] = state
                        history.append((observed_at, row))

                if delta is None:
                    continue
                limit_id = (
                    rate_limits.get("limit_id")
                    if isinstance(rate_limits, dict)
                    else None
                )
                if not isinstance(limit_id, str) or not limit_id:
                    limit_id = "unknown"
                key = (thread_id, model, service_tier, limit_id)
                aggregate = activity[key]
                aggregate["updates"] += 1
                for field in TOKEN_FIELDS:
                    aggregate[field] += delta[field]
    except OSError as exc:
        raise LimitctlError(f"failed to read rollout {path}: {exc}") from exc

    return history, activity


def scan_rollouts(
    codex_home: Path,
    since: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates: list[tuple[datetime, dict[str, Any]]] = []
    activity: dict[tuple[str, ...], dict[str, int]] = defaultdict(
        lambda: {"updates": 0, **{field: 0 for field in TOKEN_FIELDS}}
    )
    for path in find_rollouts(codex_home, since):
        file_history, file_activity = read_rollout(path, since)
        candidates.extend(file_history)
        for key, values in file_activity.items():
            aggregate = activity[key]
            aggregate["updates"] += values["updates"]
            for field in TOKEN_FIELDS:
                aggregate[field] += values[field]

    history = reduce_history(candidates)
    activity_rows = [
        {
            "threadId": key[0],
            "model": key[1],
            "serviceTier": key[2],
            "limitId": key[3],
            "updates": values["updates"],
            "inputTokens": values["input_tokens"],
            "cachedInputTokens": values["cached_input_tokens"],
            "outputTokens": values["output_tokens"],
            "reasoningOutputTokens": values["reasoning_output_tokens"],
            "totalTokens": values["total_tokens"],
        }
        for key, values in activity.items()
    ]
    activity_rows.sort(
        key=lambda row: (
            -row["totalTokens"],
            row["threadId"],
            row["model"],
            row["serviceTier"],
            row["limitId"],
        )
    )
    return history, activity_rows


def reduce_history(
    candidates: list[tuple[datetime, dict[str, Any]]],
) -> list[dict[str, Any]]:
    candidates.sort(key=lambda item: (item[0], item[1]["threadId"]))
    current: dict[tuple[str, int], dict[str, Any]] = {}
    result: list[dict[str, Any]] = []
    for _, row in candidates:
        key = (row["limitId"], row["windowDurationMins"])
        previous = current.get(key)
        if previous is None or is_newer_state(previous, row):
            current[key] = row
            result.append(row)
    return result


def is_newer_state(previous: dict[str, Any], candidate: dict[str, Any]) -> bool:
    old_reset = previous["resetsAt"]
    new_reset = candidate["resetsAt"]
    if old_reset is not None and new_reset is not None:
        if new_reset < old_reset - RESET_TOLERANCE_SECONDS:
            return False
        if new_reset > old_reset + RESET_TOLERANCE_SECONDS:
            return True
    return candidate["usedPercent"] > previous["usedPercent"]


def format_percent(value: int | float) -> str:
    return f"{value:g}" if isinstance(value, float) else str(value)


def format_history_row(row: dict[str, Any]) -> str:
    resets = "-"
    if row["resetsAt"] is not None:
        resets = format_timestamp(datetime.fromtimestamp(row["resetsAt"], timezone.utc))
    return "\t".join(
        [
            row["observedAt"],
            row["limitId"],
            f"window={format_duration(row['windowDurationMins'])}",
            f"used={format_percent(row['usedPercent'])}%",
            f"remaining={format_percent(row['remainingPercent'])}%",
            f"resets={resets}",
            f"thread={row['threadId']}",
        ]
    )


def format_activity_row(row: dict[str, Any]) -> str:
    return "\t".join(
        [
            row["threadId"],
            f"model={row['model']}",
            f"tier={row['serviceTier']}",
            f"limit={row['limitId']}",
            f"updates={row['updates']}",
            f"tokens={row['totalTokens']}",
            f"input={row['inputTokens']}",
            f"cached={row['cachedInputTokens']}",
            f"output={row['outputTokens']}",
            f"reasoning={row['reasoningOutputTokens']}",
        ]
    )
