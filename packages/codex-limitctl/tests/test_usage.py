from __future__ import annotations

import unittest
from datetime import datetime, timezone

from codex_limitctl.errors import LimitctlError
from codex_limitctl.usage import format_usage_day, normalize_usage


class UsageTests(unittest.TestCase):
    def test_normalizes_sorts_and_filters_daily_buckets(self) -> None:
        result = normalize_usage(
            {
                "summary": {"lifetimeTokens": 999},
                "dailyUsageBuckets": [
                    {"startDate": "2026-07-20", "tokens": 20},
                    {"startDate": "2026-07-18", "tokens": 10},
                    {"startDate": "2026-07-19", "tokens": 0},
                ],
            },
            datetime(2026, 7, 19, 12, tzinfo=timezone.utc),
        )

        self.assertEqual(
            result,
            [
                {"date": "2026-07-19", "tokens": 0},
                {"date": "2026-07-20", "tokens": 20},
            ],
        )
        self.assertEqual(format_usage_day(result[1]), "2026-07-20\ttokens=20")

    def test_rejects_invalid_or_duplicate_buckets(self) -> None:
        since = datetime(2026, 7, 1, tzinfo=timezone.utc)
        payloads = [
            {"dailyUsageBuckets": "bad"},
            {"dailyUsageBuckets": [{"startDate": "bad", "tokens": 1}]},
            {"dailyUsageBuckets": [{"startDate": "2026-07-20", "tokens": -1}]},
            {
                "dailyUsageBuckets": [
                    {"startDate": "2026-07-20", "tokens": 1},
                    {"startDate": "2026-07-20", "tokens": 2},
                ]
            },
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(LimitctlError):
                    normalize_usage(payload, since)

    def test_accepts_missing_or_null_daily_buckets(self) -> None:
        since = datetime(2026, 7, 1, tzinfo=timezone.utc)
        self.assertEqual(normalize_usage({"summary": {}}, since), [])
        self.assertEqual(
            normalize_usage({"summary": {}, "dailyUsageBuckets": None}, since),
            [],
        )


if __name__ == "__main__":
    unittest.main()
