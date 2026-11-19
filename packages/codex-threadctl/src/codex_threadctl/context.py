from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator


# Mirrors TokenUsage::percent_of_context_window_remaining in Codex 0.144.
BASELINE_TOKENS = 12_000
READ_CHUNK_BYTES = 64 * 1024
RELEVANT_RECORD_TYPES = (b"token_count", b"context_compacted", b'"compacted"')


def reverse_lines(path: Path) -> Iterator[bytes]:
    with path.open("rb") as handle:
        handle.seek(0, 2)
        position = handle.tell()
        remainder = b""
        while position > 0:
            size = min(position, READ_CHUNK_BYTES)
            position -= size
            handle.seek(position)
            parts = (handle.read(size) + remainder).split(b"\n")
            remainder = parts[0]
            for line in reversed(parts[1:]):
                if line:
                    yield line
        if remainder:
            yield remainder


def timestamp_seconds(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return int(parsed.timestamp())


def percent_left(used_tokens: int, window_tokens: int) -> int:
    if window_tokens <= BASELINE_TOKENS:
        return 0
    effective_window = window_tokens - BASELINE_TOKENS
    used = max(0, used_tokens - BASELINE_TOKENS)
    remaining = max(0, effective_window - used)
    return min(100, (remaining * 100 + effective_window // 2) // effective_window)


def rollout_records(lines: Iterable[bytes], markers: tuple[bytes, ...]) -> Iterator[dict[str, Any]]:
    for line in lines:
        if not any(marker in line for marker in markers):
            continue
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(record, dict) and isinstance(record.get("payload"), dict):
            yield record


def read_context_state(
    path: str | None,
    *,
    now: int | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not path:
        return None, None
    try:
        records = rollout_records(reverse_lines(Path(path)), RELEVANT_RECORD_TYPES)
        return context_from_records(records, now=now)
    except OSError:
        return None, None


def context_from_records(
    records: Iterable[dict[str, Any]],
    *,
    newest_first: bool = True,
    now: int | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    latest_usage: tuple[int, int, int, int] | None = None
    compacted_at: int | None = None
    compacted_rank: int | None = None
    compaction_event: tuple[int, int] | None = None
    window_number: int | None = None

    for index, record in enumerate(records):
        rank = -index if newest_first else index
        payload = record["payload"]
        kind = record.get("type")
        if kind == "event_msg" and payload.get("type") == "token_count":
            if latest_usage is None or not newest_first:
                info = payload.get("info")
                usage = info.get("last_token_usage") if isinstance(info, dict) else None
                if isinstance(usage, dict):
                    observed_at = timestamp_seconds(record.get("timestamp"))
                    used_tokens = usage.get("total_tokens")
                    window_tokens = info.get("model_context_window")
                    if (
                        observed_at is not None
                        and isinstance(used_tokens, int)
                        and used_tokens >= 0
                        and isinstance(window_tokens, int)
                        and window_tokens > 0
                    ):
                        latest_usage = rank, observed_at, used_tokens, window_tokens
        elif kind == "event_msg" and payload.get("type") == "context_compacted":
            if compaction_event is None or not newest_first:
                observed_at = timestamp_seconds(record.get("timestamp"))
                if observed_at is not None:
                    compaction_event = rank, observed_at
        elif kind == "compacted" and (compacted_at is None or not newest_first):
            observed_at = timestamp_seconds(record.get("timestamp"))
            if observed_at is not None or compacted_at is None:
                compacted_at = observed_at
                compacted_rank = rank
                value = payload.get("window_number")
                window_number = value if isinstance(value, int) and value >= 0 else None

        if newest_first and latest_usage is not None and compacted_at is not None:
            break

    current_time = int(time.time()) if now is None else now
    context = None
    if latest_usage is not None:
        usage_rank, observed_at, used_tokens, window_tokens = latest_usage
        if compacted_rank is None or usage_rank > compacted_rank:
            context = {
                "usedTokens": used_tokens,
                "windowTokens": window_tokens,
                "percentLeft": percent_left(used_tokens, window_tokens),
                "observedAt": observed_at,
                "observedAgoSeconds": max(0, current_time - observed_at),
            }

    last_compacted_at = compacted_at
    if compaction_event is not None:
        event_rank, event_at = compaction_event
        # Match the reverse scan's boundary once it finds both observations.
        if compacted_at is None or (
            compacted_rank is not None
            and event_at >= compacted_at
            and (latest_usage is None or event_rank >= min(latest_usage[0], compacted_rank))
        ):
            last_compacted_at = event_at
    compaction = None
    if last_compacted_at is not None:
        compaction = {
            "windowNumber": window_number,
            "lastAt": last_compacted_at,
            "lastAgoSeconds": max(0, current_time - last_compacted_at),
        }
    return context, compaction
