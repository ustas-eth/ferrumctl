import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_threadctl import context
from codex_threadctl.observations import read_rollout_observations

if sys.version_info >= (3, 14):
    from compression import zstd
else:
    from backports import zstd


class ContextTests(unittest.TestCase):
    def test_percent_left_matches_codex_baseline_math(self):
        self.assertEqual(context.percent_left(12_000, 200_000), 100)
        self.assertEqual(context.percent_left(106_000, 200_000), 50)
        self.assertEqual(context.percent_left(200_000, 200_000), 0)

    def test_reads_latest_usage_and_compaction_from_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout.jsonl"
            records = [
                {
                    "timestamp": "2026-01-01T00:00:00Z",
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "last_token_usage": {"total_tokens": 50_000},
                            "model_context_window": 200_000,
                        },
                    },
                },
                {
                    "timestamp": "2026-01-01T00:01:00Z",
                    "type": "compacted",
                    "payload": {"window_number": 3},
                },
                {
                    "timestamp": "2026-01-01T00:01:01Z",
                    "type": "event_msg",
                    "payload": {"type": "context_compacted"},
                },
                {"bad": "token_count"},
                {
                    "timestamp": "2026-01-01T00:02:00Z",
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "last_token_usage": {"total_tokens": 22_000},
                            "model_context_window": 200_000,
                        },
                    },
                },
            ]
            path.write_text("\n".join(json.dumps(record) for record in records))

            usage, compaction = context.read_context_state(path.as_posix(), now=1767225720)

        self.assertEqual(usage["usedTokens"], 22_000)
        self.assertEqual(usage["windowTokens"], 200_000)
        self.assertEqual(usage["observedAgoSeconds"], 0)
        self.assertEqual(compaction["windowNumber"], 3)
        self.assertEqual(compaction["lastAt"], 1767225661)

    def test_missing_or_unreadable_rollout_omits_state(self):
        self.assertEqual(context.read_context_state(None), (None, None))
        self.assertEqual(context.read_context_state("/does/not/exist"), (None, None))

    def test_compaction_newer_than_usage_temporarily_omits_old_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout.jsonl"
            records = [
                {
                    "timestamp": "2026-01-01T00:00:00Z",
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "last_token_usage": {"total_tokens": 190_000},
                            "model_context_window": 200_000,
                        },
                    },
                },
                {
                    "timestamp": "2026-01-01T00:01:00Z",
                    "type": "compacted",
                    "payload": {"window_number": 4},
                },
            ]
            path.write_text("\n".join(json.dumps(record) for record in records))
            usage, compaction = context.read_context_state(path.as_posix())

        self.assertIsNone(usage)
        self.assertEqual(compaction["windowNumber"], 4)

    def test_reverse_lines_handles_long_lines_and_missing_final_newline(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout.jsonl"
            lines = [b"a" * 70_000, b"second", b"third"]
            path.write_bytes(b"\n".join(lines))
            self.assertEqual(list(context.reverse_lines(path)), list(reversed(lines)))

    def test_compressed_rollout_matches_plain_before_and_after_new_usage(self):
        records = [
            ("event_msg", {"type": "token_count", "info": {
                "last_token_usage": {"total_tokens": 70_000}, "model_context_window": 200_000,
            }}),
            ("compacted", {"window_number": 4}),
            ("event_msg", {"type": "context_compacted"}),
            ("turn_context", {"model": "test-model", "effort": "high"}),
            ("event_msg", {"type": "token_count", "info": {
                "last_token_usage": {"total_tokens": 20_000}, "model_context_window": 200_000,
            }}),
        ]
        lines = [
            (json.dumps({"timestamp": f"2026-01-01T00:00:{i:02}Z", "type": kind,
                         "payload": payload}) + "\n").encode()
            for i, (kind, payload) in enumerate(records)
        ]
        with tempfile.TemporaryDirectory() as tmp, patch.object(context.time, "time", return_value=1767225610):
            plain = Path(tmp) / "rollout.jsonl"
            compressed = plain.with_suffix(".jsonl.zst")
            for end in (4, 5):
                with self.subTest(records=end):
                    plain.write_bytes(b"".join(lines[:end]))
                    expected = read_rollout_observations(str(plain))
                    compressed.write_bytes(zstd.compress(b"".join(lines[:2])) + zstd.compress(b"".join(lines[2:end])))
                    plain.unlink()
                    actual = read_rollout_observations(str(plain))
                    self.assertEqual(actual, expected)
                    self.assertEqual(actual[1]["windowNumber"], 4)
                    self.assertEqual(actual[3]["model"], "test-model")
                    self.assertEqual(actual[0]["usedTokens"] if actual[0] else None, 20_000 if end == 5 else None)

            compressed.write_bytes(compressed.read_bytes()[:-2])
            usage, compaction, context_error, settings, settings_error = read_rollout_observations(str(plain))
            self.assertEqual((usage, compaction, settings), (None, None, None))
            self.assertIn("invalid Zstandard stream", context_error)
            self.assertEqual(context_error, settings_error)

            plain.write_bytes(b"".join(lines[:4]))
            self.assertEqual(read_rollout_observations(str(compressed)), read_rollout_observations(str(plain)))
