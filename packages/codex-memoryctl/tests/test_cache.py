import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest import mock

from codex_memoryctl.cache import (
    CachedArtifact,
    artifact_key,
    clear_cache,
    default_database_path,
    get_artifact,
    inspect_cache,
    put_artifact,
)


class CacheTests(unittest.TestCase):
    def artifact(self, key: str, text: str = "retained work") -> CachedArtifact:
        return CachedArtifact(
            key=key,
            operation="summarize-v1",
            text=text,
            model="gpt-test",
            effort="medium",
            created_at="2026-01-02T03:04:05+00:00",
            elapsed_seconds=1.25,
            attempts=1,
            usage={"input_tokens": 10, "output_tokens": 4},
            response_id="resp_test",
        )

    def test_default_database_uses_xdg_state_home(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"XDG_STATE_HOME": directory}):
                self.assertEqual(
                    default_database_path(),
                    Path(directory) / "codex-memoryctl" / "derived.sqlite3",
                )

    def test_key_tracks_order_model_and_prompt(self) -> None:
        common = ("diff-v1", ["a", "b"], "model", "medium", "instructions")
        key = artifact_key(*common, "prompt")
        self.assertEqual(key, artifact_key(*common, "prompt"))
        self.assertNotEqual(
            key,
            artifact_key(
                "diff-v1",
                ["b", "a"],
                "model",
                "medium",
                "instructions",
                "prompt",
            ),
        )
        self.assertNotEqual(
            key,
            artifact_key(*common, "different prompt"),
        )

    def test_round_trip_and_replace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "derived.sqlite3"
            artifact = self.artifact("key")
            put_artifact(
                path,
                artifact,
                memory_ids=["sha256:a"],
                instructions="instructions",
                prompt="prompt",
            )
            self.assertEqual(get_artifact(path, "key"), artifact)

            replacement = self.artifact("key", "updated")
            put_artifact(
                path,
                replacement,
                memory_ids=["sha256:a"],
                instructions="instructions",
                prompt="prompt",
            )
            self.assertEqual(get_artifact(path, "key"), replacement)

    def test_default_database_is_private(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"XDG_STATE_HOME": directory}):
                path = default_database_path()
                put_artifact(
                    path,
                    self.artifact("key"),
                    memory_ids=["sha256:a"],
                    instructions="instructions",
                    prompt="prompt",
                )
                self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_concurrent_writers_share_a_new_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "derived.sqlite3"

            def write(position: int) -> None:
                put_artifact(
                    path,
                    self.artifact(f"key-{position}", f"text-{position}"),
                    memory_ids=[f"sha256:{position}"],
                    instructions="instructions",
                    prompt="prompt",
                )

            with ThreadPoolExecutor(max_workers=8) as executor:
                list(executor.map(write, range(32)))

            for position in range(32):
                artifact = get_artifact(path, f"key-{position}")
                self.assertIsNotNone(artifact)
                assert artifact is not None
                self.assertEqual(artifact.text, f"text-{position}")

    def test_inspect_and_clear_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "derived.sqlite3"
            missing = inspect_cache(path)
            self.assertFalse(missing.exists)
            self.assertEqual(missing.entry_count, 0)
            self.assertFalse(path.exists())

            for position, operation in enumerate(("summarize-v1", "diff-v1")):
                artifact = replace(
                    self.artifact(f"key-{position}"),
                    operation=operation,
                )
                put_artifact(
                    path,
                    artifact,
                    memory_ids=[f"sha256:{position}"],
                    instructions="instructions",
                    prompt="prompt",
                )

            info = inspect_cache(path)
            self.assertTrue(info.exists)
            self.assertEqual(info.entry_count, 2)
            self.assertGreater(info.size_bytes, 0)
            self.assertEqual(info.operations, {"diff-v1": 1, "summarize-v1": 1})
            self.assertEqual(clear_cache(path), 2)
            self.assertEqual(inspect_cache(path).entry_count, 0)
            self.assertEqual(clear_cache(Path(directory) / "missing.sqlite3"), 0)
