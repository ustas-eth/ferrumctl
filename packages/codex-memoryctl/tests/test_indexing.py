import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from codex_memoryctl.errors import MemoryctlError
from codex_memoryctl.indexing import (
    parse_time_boundary,
    select_checkpoints,
    uncompacted_message_count,
)
from codex_memoryctl.rollouts import (
    MemoryState,
    RolloutMemory,
    TranscriptMessage,
    memory_id,
)


def make_state(
    position: int,
    *,
    observed_at: str | None,
    line_number: int | None = None,
) -> MemoryState:
    item = {
        "type": "compaction",
        "id": f"cmp_{position}",
        "encrypted_content": str(position),
    }
    digest, size = memory_id(item)
    return MemoryState(
        thread_id="thread-test",
        rollout_path=Path("/tmp/source.jsonl"),
        origin="checkpoint",
        observed_at=observed_at,
        memory_item=item,
        memory_id=digest,
        payload_bytes=size,
        model="gpt-test",
        model_provider="openai",
        line_number=line_number,
        checkpoint_index=position,
    )


def timed_states(count: int) -> list[MemoryState]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        make_state(
            position,
            observed_at=(start + timedelta(hours=position - 1)).isoformat(),
            line_number=position * 10,
        )
        for position in range(1, count + 1)
    ]


class IndexSelectionTests(unittest.TestCase):
    def select(self, states, **overrides):
        options = {
            "from_index": None,
            "to_index": None,
            "since": None,
            "until": None,
            "limit": 10,
        }
        options.update(overrides)
        return select_checkpoints(states, **options)

    def test_default_keeps_newest_ten_in_chronological_order(self) -> None:
        selection = self.select(timed_states(14))
        self.assertEqual(selection.selected_positions, tuple(range(4, 14)))
        self.assertEqual(
            [state.checkpoint_index for state in selection.selected_states],
            list(range(5, 15)),
        )

    def test_index_bounds_filter_before_limit(self) -> None:
        states = timed_states(8)
        selection = self.select(
            states,
            from_index=2,
            to_index=6,
            limit=3,
        )
        self.assertEqual(selection.matching_positions, (1, 2, 3, 4, 5))
        self.assertEqual(selection.selected_positions, (3, 4, 5))

        complete = self.select(
            states,
            from_index=2,
            to_index=6,
            limit=0,
        )
        self.assertEqual(complete.selected_positions, (1, 2, 3, 4, 5))

    def test_date_and_timestamp_bounds_are_inclusive(self) -> None:
        states = [
            make_state(1, observed_at="2026-01-01T23:59:59Z"),
            make_state(2, observed_at="2026-01-02T12:00:00Z"),
            make_state(3, observed_at="2026-01-03T00:00:00Z"),
        ]
        one_day = self.select(
            states,
            since=parse_time_boundary("2026-01-02"),
            until=parse_time_boundary("2026-01-02"),
            limit=0,
        )
        self.assertEqual(one_day.selected_positions, (1,))

        through_offset = self.select(
            states,
            until=parse_time_boundary("2026-01-02T14:00:00+02:00"),
            limit=0,
        )
        self.assertEqual(through_offset.selected_positions, (0, 1))

    def test_invalid_ranges_and_missing_times_fail_closed(self) -> None:
        states = timed_states(3)
        with self.assertRaisesRegex(MemoryctlError, "--from-index"):
            self.select(states, from_index=3, to_index=2)
        with self.assertRaisesRegex(MemoryctlError, "--since"):
            self.select(
                states,
                since=parse_time_boundary("2026-01-02"),
                until=parse_time_boundary("2026-01-01"),
            )
        with self.assertRaisesRegex(MemoryctlError, "no timestamp"):
            self.select(
                [make_state(1, observed_at=None)],
                since=parse_time_boundary("2026-01-01"),
            )
        with self.assertRaisesRegex(MemoryctlError, "no portable checkpoints"):
            self.select(states, from_index=20)

    def test_time_parser_rejects_naive_or_invalid_values(self) -> None:
        for value in ("2026-13-01", "2026-01-01T12:00:00", "tomorrow"):
            with self.subTest(value=value):
                with self.assertRaises(MemoryctlError):
                    parse_time_boundary(value)


class UncompactedTailTests(unittest.TestCase):
    def test_counts_messages_after_latest_portable_checkpoint(self) -> None:
        state = make_state(1, observed_at="2026-01-01T00:00:00Z", line_number=10)
        messages = tuple(
            TranscriptMessage(line, None, "user", None, str(line))
            for line in (8, 11, 12)
        )
        rollout = RolloutMemory(
            "thread-test",
            Path("/tmp/source.jsonl"),
            (state,),
            messages=messages,
        )
        self.assertEqual(uncompacted_message_count(rollout), 2)
