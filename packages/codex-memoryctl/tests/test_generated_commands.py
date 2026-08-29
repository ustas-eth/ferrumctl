import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest import mock

from codex_memoryctl import generated_commands, parser
from codex_memoryctl.cache import CachedArtifact
from codex_memoryctl.generation import GenerationResult
from codex_memoryctl.rollouts import (
    MemoryState,
    RolloutMemory,
    TranscriptMessage,
    memory_id,
)


def make_state(name: str, position: int) -> MemoryState:
    item = {"type": "compaction", "id": f"cmp_{name}", "encrypted_content": name}
    digest, size = memory_id(item)
    return MemoryState(
        thread_id="thread-test",
        rollout_path=Path("/tmp/source.jsonl"),
        origin="checkpoint",
        observed_at=f"2026-01-02T03:04:{position:02d}Z",
        memory_item=item,
        memory_id=digest,
        payload_bytes=size,
        model="gpt-test",
        model_provider="openai",
        line_number=position * 10,
        checkpoint_index=position,
    )


def generated(text: str, *, cache_hit: bool) -> GenerationResult:
    return GenerationResult(
        CachedArtifact(
            key=f"key-{text}",
            operation="summarize-v1",
            text=text,
            model="gpt-test",
            effort="medium",
            created_at="2026-01-02T03:04:05+00:00",
            elapsed_seconds=1.0,
            attempts=1,
            usage={"input_tokens": 10},
            response_id="resp_test",
        ),
        cache_hit,
    )


class GeneratedCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_summarize_prints_text_and_structured_metadata(self) -> None:
        state = make_state("one", 1)
        args = parser.build_parser().parse_args(
            ["summarize", "thread@index:1", "--database", "/tmp/test.sqlite3"]
        )
        with (
            mock.patch.object(
                generated_commands,
                "load_state",
                mock.AsyncMock(return_value=state),
            ),
            mock.patch.object(
                generated_commands,
                "generated_text",
                mock.AsyncMock(return_value=generated("concise state", cache_hit=False)),
            ),
            redirect_stdout(io.StringIO()) as output,
        ):
            result = await generated_commands.cmd_summarize(args)
        self.assertEqual(result, 0)
        self.assertEqual(output.getvalue(), "concise state\n")

        args.json = True
        with (
            mock.patch.object(
                generated_commands,
                "load_state",
                mock.AsyncMock(return_value=state),
            ),
            mock.patch.object(
                generated_commands,
                "generated_text",
                mock.AsyncMock(return_value=generated("concise state", cache_hit=True)),
            ),
            redirect_stdout(io.StringIO()) as output,
        ):
            await generated_commands.cmd_summarize(args)
        parsed = json.loads(output.getvalue())
        self.assertEqual(parsed["text"], "concise state")
        self.assertTrue(parsed["generation"]["cacheHit"])
        self.assertEqual(parsed["state"]["checkpointIndex"], 1)

    async def test_summarize_reports_cache_bypass(self) -> None:
        state = make_state("one", 1)
        args = parser.build_parser().parse_args(
            ["summarize", "thread@index:1", "--no-cache", "--json"]
        )
        with (
            mock.patch.object(
                generated_commands,
                "load_state",
                mock.AsyncMock(return_value=state),
            ),
            mock.patch.object(
                generated_commands,
                "generated_text",
                mock.AsyncMock(return_value=generated("fresh state", cache_hit=False)),
            ) as built,
            redirect_stdout(io.StringIO()) as output,
        ):
            await generated_commands.cmd_summarize(args)
        parsed = json.loads(output.getvalue())
        self.assertFalse(parsed["cacheEnabled"])
        self.assertIsNone(parsed["database"])
        self.assertTrue(built.call_args.args[0].no_cache)

    async def test_summarize_warns_when_latest_checkpoint_has_a_tail(self) -> None:
        state = make_state("one", 1)
        with tempfile.TemporaryDirectory() as directory:
            rollout_path = Path(directory) / "rollout.jsonl"
            rollout_path.write_text("{}\n")
            state = replace(state, rollout_path=rollout_path)
            rollout = RolloutMemory(
                "thread-test",
                rollout_path,
                (state,),
                messages=(
                    TranscriptMessage(11, None, "user", None, "new instruction"),
                ),
            )
            args = parser.build_parser().parse_args(
                ["summarize", "thread@latest", "--json"]
            )
            with (
                mock.patch.object(
                    generated_commands,
                    "load_state",
                    mock.AsyncMock(return_value=state),
                ),
                mock.patch.object(
                    generated_commands,
                    "load_rollout",
                    return_value=rollout,
                ),
                mock.patch.object(
                    generated_commands,
                    "generated_text",
                    mock.AsyncMock(return_value=generated("older state", cache_hit=True)),
                ),
                redirect_stdout(io.StringIO()) as output,
            ):
                await generated_commands.cmd_summarize(args)

            parsed = json.loads(output.getvalue())
            self.assertFalse(parsed["sourceAdvanced"])
            self.assertTrue(parsed["hasUncompactedTail"])
            self.assertEqual(parsed["uncompactedMessageCount"], 1)

            args.json = False
            with (
                mock.patch.object(
                    generated_commands,
                    "load_state",
                    mock.AsyncMock(return_value=state),
                ),
                mock.patch.object(
                    generated_commands,
                    "load_rollout",
                    return_value=rollout,
                ),
                mock.patch.object(
                    generated_commands,
                    "generated_text",
                    mock.AsyncMock(return_value=generated("older state", cache_hit=True)),
                ),
                redirect_stdout(io.StringIO()),
                redirect_stderr(io.StringIO()) as errors,
            ):
                await generated_commands.cmd_summarize(args)
            self.assertIn("does not describe the uncompacted tail", errors.getvalue())

    async def test_summarize_reports_when_latest_advances_during_generation(self) -> None:
        selected = make_state("selected", 1)
        newer = make_state("newer", 2)
        with tempfile.TemporaryDirectory() as directory:
            rollout_path = Path(directory) / "rollout.jsonl"
            rollout_path.write_text("{}\n")
            selected = replace(selected, rollout_path=rollout_path)
            newer = replace(newer, rollout_path=rollout_path)
            rollout = RolloutMemory("thread-test", rollout_path, (selected, newer))
            args = parser.build_parser().parse_args(
                ["summarize", "thread@latest", "--json"]
            )
            with (
                mock.patch.object(
                    generated_commands,
                    "load_state",
                    mock.AsyncMock(return_value=selected),
                ),
                mock.patch.object(
                    generated_commands,
                    "load_rollout",
                    return_value=rollout,
                ),
                mock.patch.object(
                    generated_commands,
                    "generated_text",
                    mock.AsyncMock(return_value=generated("selected state", cache_hit=True)),
                ),
                redirect_stdout(io.StringIO()) as output,
            ):
                await generated_commands.cmd_summarize(args)

            parsed = json.loads(output.getvalue())
            self.assertTrue(parsed["sourceAdvanced"])
            self.assertIsNone(parsed["uncompactedMessageCount"])

    async def test_diff_keeps_older_and_newer_sources_directed(self) -> None:
        older = make_state("older", 1)
        newer = make_state("newer", 2)
        args = parser.build_parser().parse_args(
            [
                "diff",
                "thread@index:1",
                "thread@index:2",
                "--database",
                "/tmp/test.sqlite3",
                "--json",
            ]
        )
        with (
            mock.patch.object(
                generated_commands,
                "load_state",
                mock.AsyncMock(side_effect=[older, newer]),
            ),
            mock.patch.object(
                generated_commands,
                "generated_text",
                mock.AsyncMock(return_value=generated("material change", cache_hit=False)),
            ) as built,
            redirect_stdout(io.StringIO()) as output,
        ):
            result = await generated_commands.cmd_diff(args)
        self.assertEqual(result, 0)
        self.assertEqual(built.call_args.kwargs["states"], [older, newer])
        parsed = json.loads(output.getvalue())
        self.assertEqual(parsed["older"]["checkpointIndex"], 1)
        self.assertEqual(parsed["newer"]["checkpointIndex"], 2)
        self.assertEqual(parsed["text"], "material change")

    async def test_index_renders_rollout_order_and_cache_counts(self) -> None:
        first = make_state("first", 1)
        second = make_state("second", 2)
        with tempfile.TemporaryDirectory() as directory:
            rollout_path = Path(directory) / "rollout.jsonl"
            rollout_path.write_text("{}\n")
            rollout = RolloutMemory(
                "thread-test",
                rollout_path,
                (first, second),
            )
            args = parser.build_parser().parse_args(
                ["index", "thread-test", "--database", str(Path(directory) / "db")]
            )

            async def build(_args, *, operation, states, prompt):
                del prompt
                if operation == "summarize-v1":
                    self.assertEqual(states, [first])
                    return generated("first text", cache_hit=True)
                self.assertEqual(states, [first, second])
                return generated("second text", cache_hit=False)

            with (
                mock.patch.object(
                    generated_commands,
                    "resolve_source",
                    mock.AsyncMock(side_effect=lambda value, _args: value),
                ),
                mock.patch.object(
                    generated_commands,
                    "load_rollout",
                    return_value=rollout,
                ),
                mock.patch.object(
                    generated_commands,
                    "generated_text",
                    side_effect=build,
                ),
                redirect_stdout(io.StringIO()) as output,
            ):
                result = await generated_commands.cmd_index(args)
            self.assertEqual(result, 0)
            rendered = output.getvalue()
            self.assertLess(rendered.index("first text"), rendered.index("second text"))
            self.assertIn("[index:1", rendered)
            self.assertIn("[index:2", rendered)

            args.json = True
            advanced = RolloutMemory(
                "thread-test",
                rollout_path,
                (first, second, make_state("third", 3)),
            )
            with (
                mock.patch.object(
                    generated_commands,
                    "resolve_source",
                    mock.AsyncMock(side_effect=lambda value, _args: value),
                ),
                mock.patch.object(
                    generated_commands,
                    "load_rollout",
                    side_effect=[rollout, advanced],
                ),
                mock.patch.object(
                    generated_commands,
                    "generated_text",
                    side_effect=build,
                ),
                redirect_stdout(io.StringIO()) as output,
            ):
                await generated_commands.cmd_index(args)
            parsed = json.loads(output.getvalue())
            self.assertEqual(parsed["cachedCount"], 1)
            self.assertEqual(parsed["generatedCount"], 1)
            self.assertEqual(parsed["checkpointCount"], 2)
            self.assertEqual(parsed["matchingCheckpointCount"], 2)
            self.assertEqual(parsed["selectedCheckpointCount"], 2)
            self.assertEqual([record["position"] for record in parsed["records"]], [1, 2])
            self.assertTrue(parsed["sourceAdvanced"])

    async def test_index_limits_generation_and_keeps_global_predecessor(self) -> None:
        states = tuple(make_state(str(position), position) for position in range(1, 13))
        messages = (
            TranscriptMessage(125, "2026-01-02T03:05:00Z", "user", None, "tail"),
        )
        rollout = RolloutMemory(
            "thread-test",
            Path("/tmp/source.jsonl"),
            states,
            messages=messages,
        )
        args = parser.build_parser().parse_args(
            ["index", "thread-test", "--database", "/tmp/test.sqlite3", "--json"]
        )
        calls = []

        async def build(_args, *, operation, states, prompt):
            del prompt
            calls.append((operation, states))
            return generated(f"checkpoint {states[-1].checkpoint_index}", cache_hit=False)

        with (
            mock.patch.object(
                generated_commands,
                "resolve_source",
                mock.AsyncMock(side_effect=lambda value, _args: value),
            ),
            mock.patch.object(
                generated_commands,
                "load_rollout",
                return_value=rollout,
            ),
            mock.patch.object(
                generated_commands,
                "generated_text",
                side_effect=build,
            ),
            redirect_stdout(io.StringIO()) as output,
        ):
            await generated_commands.cmd_index(args)

        self.assertEqual(len(calls), 10)
        self.assertEqual(calls[0][0], "diff-v1")
        self.assertEqual(
            [state.checkpoint_index for state in calls[0][1]],
            [2, 3],
        )
        parsed = json.loads(output.getvalue())
        self.assertEqual(parsed["checkpointCount"], 12)
        self.assertEqual(parsed["matchingCheckpointCount"], 12)
        self.assertEqual(parsed["selectedCheckpointCount"], 10)
        self.assertEqual(
            [record["position"] for record in parsed["records"]],
            list(range(3, 13)),
        )
        self.assertEqual(parsed["selection"]["firstIndex"], 3)
        self.assertTrue(parsed["selection"]["hasEarlier"])
        self.assertTrue(parsed["hasUncompactedTail"])
        self.assertEqual(parsed["uncompactedMessageCount"], 1)

    async def test_plain_index_explains_pagination_and_uncompacted_tail(self) -> None:
        states = tuple(make_state(str(position), position) for position in range(1, 12))
        rollout = RolloutMemory(
            "thread-test",
            Path("/tmp/source.jsonl"),
            states,
            messages=(TranscriptMessage(115, None, "user", None, "tail"),),
        )
        args = parser.build_parser().parse_args(["index", "thread-test"])

        async def build(_args, *, operation, states, prompt):
            del operation, prompt
            return generated(f"checkpoint {states[-1].checkpoint_index}", cache_hit=True)

        with (
            mock.patch.object(
                generated_commands,
                "resolve_source",
                mock.AsyncMock(side_effect=lambda value, _args: value),
            ),
            mock.patch.object(
                generated_commands,
                "load_rollout",
                return_value=rollout,
            ),
            mock.patch.object(
                generated_commands,
                "generated_text",
                side_effect=build,
            ),
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()) as errors,
        ):
            await generated_commands.cmd_index(args)

        self.assertIn(
            "showing checkpoint indices 2-11 (10 of 11 matching",
            errors.getvalue(),
        )
        self.assertIn("use --to-index 1", errors.getvalue())
        self.assertIn("uncompacted tail", errors.getvalue())
