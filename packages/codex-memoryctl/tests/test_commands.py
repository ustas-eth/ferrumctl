import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from codex_memoryctl import commands, parser
from codex_memoryctl.errors import InjectionUncertain, MemoryctlError
from codex_memoryctl.rollouts import MemoryState, memory_id, memory_ref


class FakeContext:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, tb):
        return None


class FakeApp:
    def __init__(self):
        self.requests = []

    async def request(self, method, params=None):
        self.requests.append((method, params))
        return {}


class FailingApp(FakeApp):
    async def request(self, method, params=None):
        if method == "thread/inject_items":
            from codex_threadctl.errors import ThreadctlError

            raise ThreadctlError("connection closed")
        return await super().request(method, params)


def make_state(name: str, *, checkpoint: bool = True) -> MemoryState:
    item = {"type": "compaction", "encrypted_content": name}
    digest, size = memory_id(item)
    history = (
        ({"type": "message", "role": "user", "content": []}, item)
        if checkpoint
        else None
    )
    return MemoryState(
        thread_id=f"source-{name}",
        rollout_path=Path("/tmp/source.jsonl"),
        origin="checkpoint" if checkpoint else "standalone",
        observed_at=None,
        memory_item=item,
        memory_id=digest,
        payload_bytes=size,
        model="gpt-test",
        model_provider="openai",
        checkpoint_index=1 if checkpoint else None,
        replacement_history=history,
    )


class InjectionTests(unittest.IsolatedAsyncioTestCase):
    async def run_inject(self, argv, states):
        args = parser.build_parser().parse_args(argv)
        app = FakeApp()
        with tempfile.TemporaryDirectory() as directory:
            target_path = Path(directory) / "target.jsonl"
            target_path.write_text("")
            with (
                mock.patch.object(
                    commands, "memoryctl_appserver", return_value=FakeContext(app)
                ),
                mock.patch.object(
                    commands,
                    "resolve_thread_reference",
                    mock.AsyncMock(side_effect=lambda _app, value, **_kwargs: value),
                ),
                mock.patch.object(
                    commands, "list_loaded", mock.AsyncMock(return_value=["target"])
                ),
                mock.patch.object(
                    commands,
                    "read_thread",
                    mock.AsyncMock(
                        return_value={
                            "id": "target",
                            "modelProvider": "openai",
                            "path": str(target_path),
                        }
                    ),
                ),
                mock.patch.object(
                    commands,
                    "load_state",
                    mock.AsyncMock(side_effect=states),
                ),
                redirect_stdout(io.StringIO()) as output,
            ):
                result = await commands.cmd_inject(args)
        return result, app, output.getvalue()

    async def test_injects_ordered_memory_batch(self) -> None:
        first = make_state("first")
        second = make_state("second")
        result, app, output = await self.run_inject(
            [
                "inject",
                "target",
                "--state",
                "first@latest",
                "--state",
                "second@latest",
                "--purpose",
                "compare\ncarefully",
            ],
            [first, second],
        )
        self.assertEqual(result, 0)
        method, params = app.requests[-1]
        self.assertEqual(method, "thread/inject_items")
        self.assertEqual(params["items"], [first.memory_item, second.memory_item])
        self.assertIn(memory_ref(first.memory_id), output)
        self.assertNotIn(first.memory_id, output)
        self.assertIn("binding=source", output)
        self.assertIn('purpose="compare\\ncarefully"', output)

    async def test_implicit_self_injection_binds_memory_to_active_turn(self) -> None:
        value = make_state("donor")
        value.memory_item["internal_chat_message_metadata_passthrough"] = {
            "turn_id": "donor-turn",
            "create_time": 1,
        }
        with (
            mock.patch.dict(commands.os.environ, {"CODEX_THREAD_ID": "target"}),
            mock.patch.object(
                commands,
                "current_active_turn",
                mock.AsyncMock(return_value={"id": "recipient-turn"}),
            ) as active_turn,
        ):
            result, app, output = await self.run_inject(
                ["inject", "--state", "source@latest"],
                [value],
            )

        self.assertEqual(result, 0)
        active_turn.assert_awaited_once_with(app, "target")
        self.assertEqual(
            app.requests[-1],
            (
                "thread/inject_items",
                {
                    "threadId": "target",
                    "items": [
                        {
                            "type": "compaction",
                            "encrypted_content": "donor",
                            "internal_chat_message_metadata_passthrough": {
                                "turn_id": None
                            },
                        }
                    ],
                },
            ),
        )
        self.assertEqual(
            value.memory_item["internal_chat_message_metadata_passthrough"],
            {"turn_id": "donor-turn", "create_time": 1},
        )
        self.assertIn("binding=current:recipient-turn", output)

    async def test_implicit_self_injection_rejects_full_checkpoint(self) -> None:
        value = make_state("checkpoint")
        with (
            mock.patch.dict(commands.os.environ, {"CODEX_THREAD_ID": "target"}),
            self.assertRaisesRegex(MemoryctlError, "explicit fresh target"),
        ):
            await self.run_inject(
                ["inject", "--state", "source@latest", "--full-checkpoint"],
                [value],
            )

    async def test_full_checkpoint_injects_exact_replacement_history(self) -> None:
        value = make_state("checkpoint")
        _, app, _ = await self.run_inject(
            [
                "inject",
                "target",
                "--state",
                "source@latest",
                "--full-checkpoint",
            ],
            [value],
        )
        self.assertIsNotNone(value.replacement_history)
        self.assertEqual(
            app.requests[-1][1]["items"], list(value.replacement_history or ())
        )

    async def test_full_checkpoint_rejects_multiple_sources(self) -> None:
        args = parser.build_parser().parse_args(
            [
                "inject",
                "target",
                "--state",
                "first",
                "--state",
                "second",
                "--full-checkpoint",
            ]
        )
        app = FakeApp()
        with (
            mock.patch.object(
                commands, "memoryctl_appserver", return_value=FakeContext(app)
            ),
            mock.patch.object(
                commands,
                "resolve_thread_reference",
                mock.AsyncMock(side_effect=lambda _app, value, **_kwargs: value),
            ),
            mock.patch.object(
                commands, "list_loaded", mock.AsyncMock(return_value=["target"])
            ),
            mock.patch.object(
                commands,
                "read_thread",
                mock.AsyncMock(return_value={"modelProvider": "openai"}),
            ),
        ):
            with self.assertRaisesRegex(MemoryctlError, "exactly one"):
                await commands.cmd_inject(args)

    async def test_rejects_non_openai_target(self) -> None:
        args = parser.build_parser().parse_args(
            ["inject", "target", "--state", "source"]
        )
        app = FakeApp()
        with (
            mock.patch.object(
                commands, "memoryctl_appserver", return_value=FakeContext(app)
            ),
            mock.patch.object(
                commands,
                "resolve_thread_reference",
                mock.AsyncMock(return_value="target"),
            ),
            mock.patch.object(
                commands, "list_loaded", mock.AsyncMock(return_value=["target"])
            ),
            mock.patch.object(
                commands,
                "read_thread",
                mock.AsyncMock(return_value={"modelProvider": "zai"}),
            ),
        ):
            with self.assertRaisesRegex(MemoryctlError, "OpenAI-specific"):
                await commands.cmd_inject(args)

    async def test_rejects_full_checkpoint_flag_with_file(self) -> None:
        args = parser.build_parser().parse_args(
            [
                "inject",
                "target",
                "--file",
                "memory.json",
                "--full-checkpoint",
            ]
        )
        app = FakeApp()
        with (
            mock.patch.object(
                commands, "memoryctl_appserver", return_value=FakeContext(app)
            ),
            mock.patch.object(
                commands,
                "resolve_thread_reference",
                mock.AsyncMock(return_value="target"),
            ),
            mock.patch.object(
                commands, "list_loaded", mock.AsyncMock(return_value=["target"])
            ),
            mock.patch.object(
                commands,
                "read_thread",
                mock.AsyncMock(return_value={"modelProvider": "openai"}),
            ),
        ):
            with self.assertRaisesRegex(MemoryctlError, "cannot be used with --file"):
                await commands.cmd_inject(args)

    async def test_rejects_memory_already_observed_in_target(self) -> None:
        value = make_state("duplicate")
        args = parser.build_parser().parse_args(
            ["inject", "target", "--state", "source"]
        )
        app = FakeApp()
        with tempfile.TemporaryDirectory() as directory:
            target_path = Path(directory) / "target.jsonl"
            target_path.write_text(
                json.dumps(
                    {
                        "type": "response_item",
                        "payload": value.memory_item,
                    }
                )
                + "\n"
            )
            with (
                mock.patch.object(
                    commands, "memoryctl_appserver", return_value=FakeContext(app)
                ),
                mock.patch.object(
                    commands,
                    "resolve_thread_reference",
                    mock.AsyncMock(
                        side_effect=lambda _app, selected, **_kwargs: selected
                    ),
                ),
                mock.patch.object(
                    commands, "list_loaded", mock.AsyncMock(return_value=["target"])
                ),
                mock.patch.object(
                    commands,
                    "read_thread",
                    mock.AsyncMock(
                        return_value={
                            "modelProvider": "openai",
                            "path": str(target_path),
                        }
                    ),
                ),
                mock.patch.object(
                    commands, "load_state", mock.AsyncMock(return_value=value)
                ),
            ):
                with self.assertRaisesRegex(MemoryctlError, "already contains"):
                    await commands.cmd_inject(args)

    async def test_connection_failure_reports_uncertain_injection(self) -> None:
        value = make_state("uncertain")
        args = parser.build_parser().parse_args(
            ["inject", "target", "--state", "source"]
        )
        app = FailingApp()
        with (
            mock.patch.object(
                commands, "memoryctl_appserver", return_value=FakeContext(app)
            ),
            mock.patch.object(
                commands,
                "resolve_thread_reference",
                mock.AsyncMock(side_effect=lambda _app, selected, **_kwargs: selected),
            ),
            mock.patch.object(
                commands, "list_loaded", mock.AsyncMock(return_value=["target"])
            ),
            mock.patch.object(
                commands,
                "read_thread",
                mock.AsyncMock(return_value={"modelProvider": "openai"}),
            ),
            mock.patch.object(
                commands, "load_state", mock.AsyncMock(return_value=value)
            ),
        ):
            with self.assertRaisesRegex(
                InjectionUncertain, "before retrying"
            ) as caught:
                await commands.cmd_inject(args)
        self.assertIn(memory_ref(value.memory_id), str(caught.exception))
        self.assertNotIn(value.memory_id, str(caught.exception))
