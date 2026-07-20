from __future__ import annotations

import unittest
from datetime import datetime, timezone

from codex_limitctl.errors import LimitctlError
from codex_limitctl.timeparse import parse_since


class SinceTests(unittest.TestCase):
    def test_parses_duration_date_and_timestamp(self) -> None:
        now = datetime(2026, 7, 20, 12, tzinfo=timezone.utc)
        self.assertEqual(
            parse_since("1d2h", now),
            datetime(2026, 7, 19, 10, tzinfo=timezone.utc),
        )
        self.assertEqual(
            parse_since("2026-07-01", now),
            datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(
            parse_since("2026-07-01T03:00:00+03:00", now),
            datetime(2026, 7, 1, tzinfo=timezone.utc),
        )

    def test_rejects_zero_and_naive_timestamps(self) -> None:
        for value in ("0s", "999999999d", "2026-07-01T03:00:00", "later"):
            with self.subTest(value=value):
                with self.assertRaises(LimitctlError):
                    parse_since(value)


if __name__ == "__main__":
    unittest.main()
