import json
import os
import tempfile
import unittest
from pathlib import Path

from codex_memoryctl.envelope import (
    build_envelope,
    read_envelope,
    validate_envelope,
    write_envelope,
)
from codex_memoryctl.errors import MemoryctlError
from codex_memoryctl.rollouts import MemoryState, memory_id


def state() -> MemoryState:
    item = {"type": "compaction", "encrypted_content": "opaque"}
    digest, size = memory_id(item)
    return MemoryState(
        thread_id="thread",
        rollout_path=Path("/tmp/rollout.jsonl"),
        origin="checkpoint",
        observed_at="2026-08-20T00:00:00Z",
        memory_item=item,
        memory_id=digest,
        payload_bytes=size,
        model="gpt-test",
        model_provider="openai",
        checkpoint_index=2,
        window_number=2,
        window_id="window",
        replacement_history=(
            {"type": "message", "role": "user", "content": []},
            item,
        ),
    )


class EnvelopeTests(unittest.TestCase):
    def test_memory_export_contains_only_compaction(self) -> None:
        envelope = build_envelope(state(), full_checkpoint=False)
        self.assertEqual(envelope["scope"], "memory")
        self.assertEqual(envelope["items"], [state().memory_item])
        self.assertEqual(validate_envelope(envelope), envelope)

    def test_full_checkpoint_preserves_replacement_history(self) -> None:
        value = state()
        envelope = build_envelope(value, full_checkpoint=True)
        self.assertEqual(envelope["scope"], "checkpoint")
        self.assertIsNotNone(value.replacement_history)
        self.assertEqual(envelope["items"], list(value.replacement_history or ()))

    def test_tampered_memory_fails_digest_validation(self) -> None:
        envelope = build_envelope(state(), full_checkpoint=False)
        envelope["items"][0]["encrypted_content"] = "changed"
        with self.assertRaisesRegex(MemoryctlError, "digest"):
            validate_envelope(envelope)

    def test_export_is_private_and_refuses_overwrite(self) -> None:
        envelope = build_envelope(state(), full_checkpoint=False)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.json"
            write_envelope(envelope, str(path), force=False)
            mode = os.stat(path).st_mode & 0o777
            self.assertEqual(mode, 0o600)
            self.assertEqual(read_envelope(str(path))["memory"], envelope["memory"])
            with self.assertRaisesRegex(MemoryctlError, "already exists"):
                write_envelope(envelope, str(path), force=False)

    def test_invalid_source_shape_is_tolerated_only_until_consumed(self) -> None:
        envelope = build_envelope(state(), full_checkpoint=False)
        envelope["source"] = "bad"
        # Source metadata is informative, but its type must still be safe for consumers.
        with self.assertRaisesRegex(MemoryctlError, "source"):
            validate_envelope(envelope)
