import tempfile
import unittest
from pathlib import Path
from unittest import mock

from codex_memoryctl import generation
from codex_memoryctl.errors import MemoryctlError
from codex_memoryctl.rollouts import MemoryState, memory_id


def make_state(name: str) -> MemoryState:
    item = {"type": "compaction", "id": f"cmp_{name}", "encrypted_content": name}
    digest, size = memory_id(item)
    return MemoryState(
        thread_id=f"thread-{name}",
        rollout_path=Path("/tmp/source.jsonl"),
        origin="checkpoint",
        observed_at=None,
        memory_item=item,
        memory_id=digest,
        payload_bytes=size,
        model="gpt-test",
        model_provider="openai",
        checkpoint_index=1,
    )


class PromptTests(unittest.TestCase):
    def test_prompts_are_compact_and_treat_nested_memory_as_content(self) -> None:
        self.assertIn("under 120 words", generation.summary_prompt())
        self.assertIn("outer retained state", generation.summary_prompt())
        self.assertIn("outer states", generation.diff_prompt())
        focused = generation.summary_prompt("network roots")
        self.assertIn('"network roots"', focused)

    def test_model_output_schema_allows_only_nonempty_text(self) -> None:
        schema = generation.TEXT_FORMAT["schema"]
        self.assertTrue(generation.TEXT_FORMAT["strict"])
        self.assertEqual(schema["required"], ["text"])
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["text"]["minLength"], 1)

    def test_inputs_bound_and_order_opaque_states(self) -> None:
        older = make_state("older")
        newer = make_state("newer")
        summary = generation.summary_input(older, "prompt")
        self.assertEqual(summary[1], older.memory_item)
        self.assertEqual(summary[0]["role"], "developer")
        self.assertEqual(summary[-1]["role"], "user")

        compared = generation.diff_input(older, newer, "prompt")
        self.assertEqual(compared[1], older.memory_item)
        self.assertEqual(compared[3], newer.memory_item)
        self.assertIn("transition", compared[2]["content"][0]["text"])

    def test_response_requires_exact_nonempty_text_field(self) -> None:
        self.assertEqual(generation._parse_text('{"text":" useful "}'), "useful")
        for invalid in ('{"text":"","other":1}', '{"summary":"x"}', "plain"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(MemoryctlError):
                    generation._parse_text(invalid)

    def test_malformed_subscription_auth_fails_without_echoing_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            secret = "not-a-valid-secret-token"
            (Path(directory) / "auth.json").write_text(
                f'{{"tokens":{{"access_token":"{secret}"}}}}',
                encoding="utf-8",
            )
            with self.assertRaises(MemoryctlError) as raised:
                generation._credentials(Path(directory))
        self.assertNotIn(secret, str(raised.exception))


class GenerationCacheTests(unittest.TestCase):
    def test_reuses_validated_cached_generation(self) -> None:
        state = make_state("cached")
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "derived.sqlite3"
            with mock.patch.object(
                generation,
                "_call_once",
                return_value=(
                    "retained state",
                    {"input_tokens": 10, "output_tokens": 3},
                    "resp_test",
                    1.25,
                ),
            ) as called:
                first = generation.generate(
                    database,
                    Path(directory),
                    operation="summarize-v1",
                    states=[state],
                    prompt="prompt",
                    model="gpt-test",
                    effort="medium",
                    refresh=False,
                )
                second = generation.generate(
                    database,
                    Path(directory),
                    operation="summarize-v1",
                    states=[state],
                    prompt="prompt",
                    model="gpt-test",
                    effort="medium",
                    refresh=False,
                )
        self.assertFalse(first.cache_hit)
        self.assertTrue(second.cache_hit)
        self.assertEqual(second.artifact.text, "retained state")
        called.assert_called_once()

    def test_refresh_replaces_matching_cached_output(self) -> None:
        state = make_state("refresh")
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "derived.sqlite3"
            with mock.patch.object(
                generation,
                "_call_once",
                side_effect=[
                    ("first", {}, "resp_1", 1.0),
                    ("second", {}, "resp_2", 2.0),
                ],
            ):
                first = generation.generate(
                    database,
                    Path(directory),
                    operation="summarize-v1",
                    states=[state],
                    prompt="prompt",
                    model="gpt-test",
                    effort="medium",
                    refresh=False,
                )
                second = generation.generate(
                    database,
                    Path(directory),
                    operation="summarize-v1",
                    states=[state],
                    prompt="prompt",
                    model="gpt-test",
                    effort="medium",
                    refresh=True,
                )
                cached = generation.generate(
                    database,
                    Path(directory),
                    operation="summarize-v1",
                    states=[state],
                    prompt="prompt",
                    model="gpt-test",
                    effort="medium",
                    refresh=False,
                )
        self.assertEqual(first.artifact.text, "first")
        self.assertEqual(second.artifact.text, "second")
        self.assertTrue(cached.cache_hit)
        self.assertEqual(cached.artifact.text, "second")

    def test_retries_one_transient_generation_failure(self) -> None:
        state = make_state("retry")
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(
                generation,
                "_call_once",
                side_effect=[
                    generation._GenerationFailure("temporary", retryable=True),
                    ("recovered", {}, "resp_2", 2.0),
                ],
            ) as called:
                result = generation.generate(
                    Path(directory) / "derived.sqlite3",
                    Path(directory),
                    operation="summarize-v1",
                    states=[state],
                    prompt="prompt",
                    model="gpt-test",
                    effort="medium",
                    refresh=False,
                )
        self.assertEqual(called.call_count, 2)
        self.assertEqual(result.artifact.attempts, 2)

    def test_does_not_retry_nontransient_generation_failure(self) -> None:
        state = make_state("no-retry")
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(
                generation,
                "_call_once",
                side_effect=generation._GenerationFailure(
                    "bad request",
                    retryable=False,
                ),
            ) as called:
                with self.assertRaisesRegex(MemoryctlError, "after 1 attempt"):
                    generation.generate(
                        Path(directory) / "derived.sqlite3",
                        Path(directory),
                        operation="summarize-v1",
                        states=[state],
                        prompt="prompt",
                        model="gpt-test",
                        effort="medium",
                        refresh=False,
                    )
        called.assert_called_once()
