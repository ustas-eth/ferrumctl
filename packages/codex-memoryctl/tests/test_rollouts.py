import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from codex_memoryctl.errors import MemoryctlError
from codex_memoryctl.rollouts import find_rollout, memory_ref, scan_rollout
from codex_memoryctl.selectors import parse_state_reference, select_state

THREAD_ID = "01a00000-0000-7000-8000-000000000001"
ORIGIN_THREAD_ID = "01a00000-0000-7000-8000-000000000002"


def memory_item(content: str) -> dict:
    return {
        "type": "compaction",
        "id": f"cmp_{content}",
        "encrypted_content": content,
        "internal_chat_message_metadata_passthrough": {"turn_id": "turn"},
    }


def write_rollout(
    path: Path, records: list[dict], *, partial: str | None = None
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
        if partial is not None:
            handle.write(partial)


class RolloutTests(unittest.TestCase):
    def test_scans_checkpoints_and_standalone_memory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / f"rollout-{THREAD_ID}.jsonl"
            first = memory_item("first")
            injected = memory_item("injected")
            write_rollout(
                path,
                [
                    {
                        "type": "session_meta",
                        "payload": {"id": THREAD_ID, "model_provider": "openai"},
                    },
                    {
                        "type": "turn_context",
                        "payload": {"model": "gpt-test"},
                    },
                    {
                        "timestamp": "2026-08-20T00:00:00Z",
                        "type": "compacted",
                        "payload": {
                            "window_number": 7,
                            "window_id": "window-7",
                            "replacement_history": [
                                {"type": "message", "role": "user", "content": []},
                                first,
                            ],
                        },
                    },
                    {
                        "timestamp": "2026-08-20T00:01:00Z",
                        "type": "response_item",
                        "payload": injected,
                    },
                ],
            )

            rollout = scan_rollout(path)

        self.assertEqual(rollout.thread_id, THREAD_ID)
        self.assertEqual(rollout.compaction_count, 1)
        self.assertEqual(len(rollout.states), 2)
        checkpoint, standalone = rollout.states
        self.assertEqual(checkpoint.origin, "checkpoint")
        self.assertEqual(checkpoint.window_number, 7)
        self.assertEqual(checkpoint.checkpoint_index, 1)
        self.assertEqual(checkpoint.retained_items, 1)
        self.assertEqual(checkpoint.model, "gpt-test")
        self.assertEqual(checkpoint.model_provider, "openai")
        self.assertEqual(standalone.origin, "standalone")
        self.assertTrue(checkpoint.visible)
        self.assertTrue(standalone.visible)
        expected = hashlib.sha256(b"injected").hexdigest()
        self.assertEqual(standalone.memory_id, f"sha256:{expected}")
        self.assertEqual(standalone.metadata()["memoryId"], f"m:{expected[:12]}")
        self.assertEqual(memory_ref(standalone.memory_id), f"m:{expected[:12]}")
        self.assertEqual(
            rollout.visible_memory_ids,
            frozenset({checkpoint.memory_id, standalone.memory_id}),
        )

    def test_visible_memory_follows_latest_compacted_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / f"rollout-{THREAD_ID}.jsonl"
            old = memory_item("old")
            before_compaction = memory_item("before-compaction")
            current = memory_item("current")
            after_compaction = memory_item("after-compaction")
            write_rollout(
                path,
                [
                    {
                        "type": "compacted",
                        "payload": {"replacement_history": [old]},
                    },
                    {"type": "response_item", "payload": before_compaction},
                    {
                        "type": "compacted",
                        "payload": {"replacement_history": [current]},
                    },
                    {"type": "response_item", "payload": after_compaction},
                ],
            )
            rollout = scan_rollout(path)

        current_id = next(
            state.memory_id
            for state in rollout.states
            if state.memory_item == current
        )
        after_id = next(
            state.memory_id
            for state in rollout.states
            if state.memory_item == after_compaction
        )
        old_ids = {
            state.memory_id
            for state in rollout.states
            if state.memory_item in (old, before_compaction)
        }
        self.assertEqual(rollout.visible_memory_ids, frozenset({current_id, after_id}))
        self.assertTrue(old_ids.isdisjoint(rollout.visible_memory_ids))
        visibility = {
            state.memory_item["encrypted_content"]: state.visible
            for state in rollout.states
        }
        self.assertEqual(
            visibility,
            {
                "old": False,
                "before-compaction": False,
                "current": True,
                "after-compaction": True,
            },
        )

    def test_visibility_belongs_to_an_observation_not_only_its_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / f"rollout-{THREAD_ID}.jsonl"
            repeated = memory_item("repeated")
            current = memory_item("current")
            write_rollout(
                path,
                [
                    {
                        "type": "compacted",
                        "payload": {"replacement_history": [repeated]},
                    },
                    {
                        "type": "compacted",
                        "payload": {"replacement_history": [current]},
                    },
                    {"type": "response_item", "payload": repeated},
                ],
            )
            rollout = scan_rollout(path)

        repeated_states = [
            state for state in rollout.states if state.memory_item == repeated
        ]
        self.assertEqual([state.visible for state in repeated_states], [False, True])
        self.assertIn(repeated_states[0].memory_id, rollout.visible_memory_ids)

    def test_checkpoint_index_counts_nonportable_compactions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / f"rollout-{THREAD_ID}.jsonl"
            write_rollout(
                path,
                [
                    {
                        "type": "compacted",
                        "payload": {"replacement_history": []},
                    },
                    {
                        "type": "compacted",
                        "payload": {
                            "replacement_history": [memory_item("portable")]
                        },
                    },
                ],
            )
            rollout = scan_rollout(path)
        self.assertEqual(rollout.compaction_count, 2)
        self.assertEqual(rollout.last_compaction_line, 2)
        self.assertEqual(rollout.states[0].checkpoint_index, 2)

    def test_latest_fails_closed_after_nonportable_compaction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / f"rollout-{THREAD_ID}.jsonl"
            write_rollout(
                path,
                [
                    {
                        "type": "compacted",
                        "payload": {
                            "window_number": 1,
                            "replacement_history": [memory_item("portable")],
                        },
                    },
                    {
                        "type": "compacted",
                        "payload": {"replacement_history": []},
                    },
                ],
            )
            rollout = scan_rollout(path)

        with self.assertRaisesRegex(MemoryctlError, "latest compaction.*no portable"):
            select_state(rollout, "latest")
        self.assertEqual(select_state(rollout, "index:1").checkpoint_index, 1)

    def test_missing_response_item_id_is_not_portable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / f"rollout-{THREAD_ID}.jsonl"
            invalid = memory_item("invalid")
            invalid["id"] = None
            write_rollout(
                path,
                [
                    {
                        "type": "compacted",
                        "payload": {"replacement_history": [invalid]},
                    }
                ],
            )
            rollout = scan_rollout(path)
        self.assertEqual(rollout.states, ())

    def test_rollout_path_id_remains_canonical_after_inherited_session_meta(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / f"rollout-{THREAD_ID}.jsonl"
            write_rollout(
                path,
                [
                    {
                        "type": "session_meta",
                        "payload": {"id": ORIGIN_THREAD_ID},
                    },
                    {
                        "type": "compacted",
                        "payload": {
                            "replacement_history": [memory_item("forked")]
                        },
                    },
                ],
            )
            rollout = scan_rollout(path)
        self.assertEqual(rollout.thread_id, THREAD_ID)
        self.assertEqual(rollout.session_meta_thread_id, ORIGIN_THREAD_ID)
        self.assertEqual(rollout.states[0].thread_id, THREAD_ID)
        self.assertEqual(
            rollout.states[0].metadata()["sessionMetaThreadId"],
            ORIGIN_THREAD_ID,
        )

    def test_matching_session_meta_id_is_not_reported_as_an_origin(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / f"rollout-{THREAD_ID}.jsonl"
            write_rollout(
                path,
                [
                    {"type": "session_meta", "payload": {"id": THREAD_ID}},
                    {
                        "type": "compacted",
                        "payload": {
                            "replacement_history": [memory_item("native")]
                        },
                    },
                ],
            )
            rollout = scan_rollout(path)

        self.assertEqual(rollout.session_meta_thread_id, THREAD_ID)
        self.assertIsNone(rollout.states[0].metadata()["sessionMetaThreadId"])

    def test_partial_final_record_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / f"rollout-{THREAD_ID}.jsonl"
            write_rollout(
                path,
                [
                    {
                        "type": "compacted",
                        "payload": {
                            "replacement_history": [memory_item("complete")]
                        },
                    }
                ],
                partial='{"type":"compacted","payload":',
            )
            rollout = scan_rollout(path)
        self.assertEqual(len(rollout.states), 1)

    def test_malformed_complete_record_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / f"rollout-{THREAD_ID}.jsonl"
            path.write_text('{"type":"compacted",bad}\n')
            with self.assertRaisesRegex(MemoryctlError, "invalid rollout JSON"):
                scan_rollout(path)

    def test_finds_active_or_archived_rollout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            path = home / "archived_sessions" / f"rollout-{THREAD_ID}.jsonl"
            write_rollout(path, [])
            self.assertEqual(find_rollout(home, THREAD_ID), path.resolve())

    def test_ambiguous_rollout_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            for name in ("sessions", "archived_sessions"):
                write_rollout(home / name / f"rollout-{THREAD_ID}.jsonl", [])
            with self.assertRaisesRegex(MemoryctlError, "multiple rollouts"):
                find_rollout(home, THREAD_ID)


class SelectorTests(unittest.TestCase):
    def make_rollout(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / f"rollout-{THREAD_ID}.jsonl"
            write_rollout(
                path,
                [
                    {
                        "type": "compacted",
                        "payload": {
                            "window_number": 2,
                            "replacement_history": [memory_item("old")],
                        },
                    },
                    {
                        "type": "compacted",
                        "payload": {
                            "window_number": 3,
                            "replacement_history": [memory_item("new")],
                        },
                    },
                ],
            )
            return scan_rollout(path)

    def test_parses_default_and_explicit_selector(self) -> None:
        self.assertEqual(parse_state_reference(THREAD_ID).selector, "latest")
        parsed = parse_state_reference(f"{THREAD_ID}@window:3")
        self.assertEqual(parsed.source, THREAD_ID)
        self.assertEqual(parsed.selector, "window:3")

    def test_selects_latest_window_index_and_digest(self) -> None:
        rollout = self.make_rollout()
        latest = select_state(rollout, "latest")
        self.assertEqual(latest.window_number, 3)
        self.assertEqual(select_state(rollout, "window:2").window_number, 2)
        self.assertEqual(select_state(rollout, "index:1").window_number, 2)
        prefix = latest.memory_id.removeprefix("sha256:")[:12]
        self.assertEqual(select_state(rollout, f"m:{prefix}"), latest)

    def test_latest_prefers_generated_checkpoint_over_standalone_memory(self) -> None:
        rollout = self.make_rollout()
        injected = replace(
            rollout.states[-1],
            origin="standalone",
            checkpoint_index=None,
            window_number=None,
            replacement_history=None,
        )
        combined = replace(
            rollout,
            states=(*rollout.states, injected),
        )
        self.assertEqual(select_state(combined, "latest"), rollout.states[-1])
        standalone_only = replace(
            combined,
            states=(injected,),
            compaction_count=0,
        )
        self.assertEqual(select_state(standalone_only, "latest"), injected)
        prefix = injected.memory_id.removeprefix("sha256:")[:12]
        self.assertEqual(
            select_state(combined, f"sha256:{prefix}", require_checkpoint=True),
            rollout.states[-1],
        )

    def test_unknown_selector_fails(self) -> None:
        rollout = self.make_rollout()
        with self.assertRaisesRegex(MemoryctlError, "unknown state selector"):
            select_state(rollout, "yesterday")
