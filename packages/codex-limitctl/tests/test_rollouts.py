from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from codex_limitctl.rollouts import (
    find_rollouts,
    read_rollout,
    reduce_history,
    scan_rollouts,
)


THREAD_ID = "019f7cfc-0430-7ba2-b588-b2ea3f907f15"


def counter(input_tokens: int, cached: int, output: int, reasoning: int) -> dict:
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached,
        "output_tokens": output,
        "reasoning_output_tokens": reasoning,
        "total_tokens": input_tokens + output,
    }


def token_event(
    timestamp: str,
    total: dict,
    last: dict,
    *,
    used: float = 10.0,
    reset: int = 1800000000,
    window: int = 10080,
) -> dict:
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {"total_token_usage": total, "last_token_usage": last},
            "rate_limits": {
                "limit_id": "codex",
                "primary": {
                    "used_percent": used,
                    "window_minutes": window,
                    "resets_at": reset,
                },
                "secondary": None,
            },
        },
    }


def write_rollout(path: Path, records: list[dict], *, partial: bool = False) -> None:
    text = "".join(json.dumps(record) + "\n" for record in records)
    if partial:
        text += '{"timestamp":"2026-07-20T00:04:00Z","type":"event_msg"'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


class RolloutUsageTests(unittest.TestCase):
    def make_path(self, directory: str) -> Path:
        return Path(directory) / f"rollout-2026-07-20T00-00-00-{THREAD_ID}.jsonl"

    def test_counts_fresh_usage_and_cumulative_deltas(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.make_path(tmp)
            first = counter(80, 0, 20, 2)
            second = counter(150, 50, 30, 5)
            write_rollout(
                path,
                [
                    {"type": "session_meta", "payload": {"id": THREAD_ID}},
                    {"type": "turn_context", "payload": {"model": "gpt-test"}},
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "thread_settings_applied",
                            "thread_settings": {"service_tier": "fast"},
                        },
                    },
                    token_event("2026-07-20T00:01:00Z", first, first),
                    token_event("2026-07-20T00:02:00Z", first, first),
                    token_event(
                        "2026-07-20T00:03:00Z", second, counter(70, 50, 10, 3)
                    ),
                ],
                partial=True,
            )
            history, activity = read_rollout(
                path, datetime(2026, 7, 20, tzinfo=timezone.utc)
            )

        self.assertEqual(len(history), 1)
        self.assertEqual(len(activity), 1)
        values = next(iter(activity.values()))
        self.assertEqual(values["updates"], 2)
        self.assertEqual(values["input_tokens"], 150)
        self.assertEqual(values["cached_input_tokens"], 50)
        self.assertEqual(values["output_tokens"], 30)
        self.assertEqual(values["reasoning_output_tokens"], 5)
        self.assertEqual(values["total_tokens"], 180)
        self.assertEqual(
            next(iter(activity)), (THREAD_ID, "gpt-test", "fast", "codex")
        )

    def test_does_not_count_inherited_or_reset_baselines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.make_path(tmp)
            write_rollout(
                path,
                [
                    token_event(
                        "2026-07-20T00:01:00Z",
                        counter(900, 500, 100, 20),
                        counter(90, 50, 10, 2),
                    ),
                    token_event(
                        "2026-07-20T00:02:00Z",
                        counter(980, 540, 120, 25),
                        counter(80, 40, 20, 5),
                    ),
                    token_event(
                        "2026-07-20T00:03:00Z",
                        counter(40, 0, 10, 1),
                        counter(40, 0, 10, 1),
                    ),
                    token_event(
                        "2026-07-20T00:04:00Z",
                        counter(65, 10, 15, 2),
                        counter(25, 10, 5, 1),
                    ),
                ],
            )
            _, activity = read_rollout(
                path, datetime(2026, 7, 20, tzinfo=timezone.utc)
            )

        values = next(iter(activity.values()))
        self.assertEqual(values["updates"], 2)
        self.assertEqual(values["total_tokens"], 130)
        self.assertEqual(values["input_tokens"], 105)
        self.assertEqual(values["output_tokens"], 25)


class RolloutHistoryTests(unittest.TestCase):
    def row(self, used: int, reset: int, observed: str) -> tuple[datetime, dict]:
        timestamp = datetime.fromisoformat(observed.replace("Z", "+00:00"))
        return timestamp, {
            "observedAt": observed,
            "threadId": f"thread-{used}-{reset}",
            "model": "gpt-test",
            "serviceTier": "default",
            "limitId": "codex",
            "windowDurationMins": 10080,
            "usedPercent": used,
            "remainingPercent": 100 - used,
            "resetsAt": reset,
        }

    def test_reducer_ignores_stale_concurrent_snapshots(self) -> None:
        candidates = [
            self.row(50, 2000, "2026-07-20T00:01:00Z"),
            self.row(40, 2000, "2026-07-20T00:02:00Z"),
            self.row(80, 1000, "2026-07-20T00:03:00Z"),
            self.row(60, 2050, "2026-07-20T00:04:00Z"),
            self.row(5, 4000, "2026-07-20T00:05:00Z"),
        ]

        result = reduce_history(candidates)

        self.assertEqual([row["usedPercent"] for row in result], [50, 60, 5])

    def test_scanner_normalizes_drifting_window_lengths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            path = (
                home
                / "sessions"
                / "2026"
                / "07"
                / "20"
                / f"rollout-2026-07-20T00-00-00-{THREAD_ID}.jsonl"
            )
            value = counter(10, 0, 1, 0)
            write_rollout(
                path,
                [token_event("2026-07-20T00:01:00Z", value, value, window=10075)],
            )
            modified = datetime(2026, 7, 20, 1, tzinfo=timezone.utc).timestamp()
            os.utime(path, (modified, modified))
            history, _ = scan_rollouts(
                home, datetime(2026, 7, 20, tzinfo=timezone.utc)
            )

        self.assertEqual(history[0]["windowDurationMins"], 10080)

    def test_file_discovery_uses_mtime_not_directory_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            recent = (
                home
                / "sessions"
                / "2020"
                / "01"
                / "01"
                / f"rollout-old-{THREAD_ID}.jsonl"
            )
            stale = home / "sessions" / "2026" / "07" / "20" / "rollout-stale.jsonl"
            write_rollout(recent, [])
            write_rollout(stale, [])
            recent_time = datetime(2026, 7, 20, 12, tzinfo=timezone.utc).timestamp()
            stale_time = datetime(2026, 7, 19, tzinfo=timezone.utc).timestamp()
            os.utime(recent, (recent_time, recent_time))
            os.utime(stale, (stale_time, stale_time))

            result = find_rollouts(
                home, datetime(2026, 7, 20, 10, tzinfo=timezone.utc)
            )

        self.assertEqual(result, [recent])


if __name__ == "__main__":
    unittest.main()
