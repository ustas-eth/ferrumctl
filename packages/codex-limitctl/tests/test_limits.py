from __future__ import annotations

import copy
import unittest

from codex_limitctl.errors import LimitctlError
from codex_limitctl.limits import (
    format_duration,
    format_window,
    normalize_rate_limits,
    select_windows,
)


def snapshot() -> dict:
    return {
        "limitId": "codex",
        "limitName": "Codex",
        "planType": "pro",
        "primary": {
            "usedPercent": 30,
            "windowDurationMins": 300,
            "resetsAt": 1785000000,
        },
        "secondary": {
            "usedPercent": 11,
            "windowDurationMins": 10080,
            "resetsAt": 1784959243,
        },
        "credits": {"hasCredits": False, "balance": "0"},
        "individualLimit": {"limit": "100", "used": "10"},
    }


def response() -> dict:
    current = snapshot()
    return {
        "rateLimits": copy.deepcopy(current),
        "rateLimitsByLimitId": {"codex": current},
        "rateLimitResetCredits": {
            "availableCount": 1,
            "credits": [{"id": "secret-reset-credit"}],
        },
    }


class NormalizeTests(unittest.TestCase):
    def test_normalizes_and_sorts_windows_by_duration(self) -> None:
        windows = normalize_rate_limits(response())

        self.assertEqual([row["windowDurationMins"] for row in windows], [300, 10080])
        self.assertEqual(windows[0]["remainingPercent"], 70)
        self.assertEqual(windows[1]["remainingPercent"], 89)
        self.assertEqual(windows[1]["planType"], "pro")

    def test_primary_secondary_order_has_no_semantic_effect(self) -> None:
        original = response()
        swapped = response()
        item = swapped["rateLimitsByLimitId"]["codex"]
        item["primary"], item["secondary"] = item["secondary"], item["primary"]

        self.assertEqual(
            normalize_rate_limits(original),
            normalize_rate_limits(swapped),
        )

    def test_omits_backend_credit_and_spending_fields(self) -> None:
        windows = normalize_rate_limits(response())
        serialized = repr(windows)

        self.assertNotIn("secret-reset-credit", serialized)
        self.assertNotIn("credits", serialized)
        self.assertNotIn("individualLimit", serialized)
        self.assertEqual(
            set(windows[0]),
            {
                "limitId",
                "limitName",
                "planType",
                "windowDurationMins",
                "usedPercent",
                "remainingPercent",
                "resetsAt",
            },
        )

    def test_uses_backward_compatible_snapshot_when_map_is_absent(self) -> None:
        value = {"rateLimits": snapshot(), "rateLimitsByLimitId": None}
        self.assertEqual(len(normalize_rate_limits(value)), 2)

    def test_deduplicates_identical_duration_rows(self) -> None:
        value = response()
        item = value["rateLimitsByLimitId"]["codex"]
        item["secondary"] = copy.deepcopy(item["primary"])
        windows = normalize_rate_limits(value)
        self.assertEqual(len(windows), 1)

    def test_rejects_conflicting_rows_for_one_duration(self) -> None:
        value = response()
        item = value["rateLimitsByLimitId"]["codex"]
        item["secondary"]["windowDurationMins"] = 300
        with self.assertRaisesRegex(LimitctlError, "conflicting 5h windows"):
            normalize_rate_limits(value)

    def test_rejects_invalid_percent(self) -> None:
        value = response()
        value["rateLimitsByLimitId"]["codex"]["primary"]["usedPercent"] = 101
        with self.assertRaisesRegex(LimitctlError, "used percentage"):
            normalize_rate_limits(value)

    def test_rejects_disagreeing_map_and_snapshot_ids(self) -> None:
        value = response()
        value["rateLimitsByLimitId"]["codex"]["limitId"] = "other"
        with self.assertRaisesRegex(LimitctlError, "disagrees"):
            normalize_rate_limits(value)


class SelectionAndFormattingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.windows = normalize_rate_limits(response())

    def test_selects_by_limit_and_duration(self) -> None:
        selected = select_windows(
            self.windows,
            limit_id="codex",
            duration_minutes=10080,
        )
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["remainingPercent"], 89)

    def test_formats_compound_duration(self) -> None:
        self.assertEqual(format_duration(10080), "7d")
        self.assertEqual(format_duration(300), "5h")
        self.assertEqual(format_duration(1530), "1d1h30m")
        self.assertEqual(format_duration(None), "unknown")

    def test_formats_plain_window_line(self) -> None:
        line = format_window(self.windows[1])
        self.assertEqual(
            line,
            "codex\tname=\"Codex\"\twindow=7d\tused=11%\tremaining=89%\t"
            "resets=2026-07-25T06:00:43Z",
        )


if __name__ == "__main__":
    unittest.main()
