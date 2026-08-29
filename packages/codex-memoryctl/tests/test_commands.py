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
from codex_memoryctl.selectors import StateReference


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
    item = {"type": "compaction", "id": f"cmp_{name}", "encrypted_content": name}
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
    async def test_existing_root_path_is_not_resolved_as_an_agent(self) -> None:
        reference = StateReference("/root/rollout.jsonl", "latest")
        args = parser.build_parser().parse_args(["show", "/tmp/source.jsonl"])
        with (
            mock.patch.object(commands.Path, "is_file", return_value=True),
            mock.patch.object(
                commands,
                "resolve_thread_reference",
                mock.AsyncMock(),
            ) as resolved,
        ):
            result = await commands.resolve_source(reference, args, FakeApp())

        self.assertEqual(result, reference)
        resolved.assert_not_awaited()

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
                            "status": {"type": "active"},
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
                "--to",
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
        items = params["items"]
        self.assertEqual(len(items), 5)
        self.assertEqual(items[1], first.memory_item)
        self.assertEqual(items[3], second.memory_item)
        opening = json.loads(items[0]["content"][0]["text"])
        transition = json.loads(items[2]["content"][0]["text"])
        closing = json.loads(items[4]["content"][0]["text"])
        self.assertEqual(opening["event"], "memoryctl.perspective.open")
        self.assertEqual(opening["openedMemory"]["position"], 1)
        self.assertEqual(
            transition["event"], "memoryctl.perspective.transition"
        )
        self.assertEqual(transition["closedMemory"]["position"], 1)
        self.assertEqual(transition["openedMemory"]["position"], 2)
        self.assertEqual(closing["event"], "memoryctl.perspective.close")
        self.assertEqual(
            closing["callerPurpose"],
            {"origin": "caller-supplied", "text": "compare\ncarefully"},
        )
        self.assertEqual(
            closing["closedMemory"]["sourceBasis"],
            "local-rollout",
        )
        self.assertIn(memory_ref(first.memory_id), output)
        self.assertNotIn(first.memory_id, output)
        self.assertIn("binding=source", output)
        self.assertIn("source-basis=local-rollout", output)
        self.assertIn("framing=boundaries", output)
        self.assertIn("purpose-delivery=attributed-boundary", output)
        self.assertIn('purpose="compare\\ncarefully"', output)

    async def test_self_injection_binds_memory_to_active_turn(self) -> None:
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
                [
                    "inject",
                    "--self",
                    "--state",
                    "source@latest",
                    "--purpose",
                    "recover an earlier diagnosis",
                ],
                [value],
            )

        self.assertEqual(result, 0)
        active_turn.assert_awaited_once_with(app, "target")
        method, params = app.requests[-1]
        self.assertEqual(method, "thread/inject_items")
        self.assertEqual(params["threadId"], "target")
        self.assertEqual(len(params["items"]), 3)
        self.assertEqual(
            params["items"][1],
            {
                "type": "compaction",
                "id": "cmp_donor",
                "encrypted_content": "donor",
                "internal_chat_message_metadata_passthrough": {
                    "turn_id": None
                },
            },
        )
        opening = params["items"][0]
        self.assertEqual(opening["type"], "agent_message")
        self.assertEqual(opening["author"], "memoryctl")
        self.assertEqual(opening["recipient"], "target")
        opened = json.loads(opening["content"][0]["text"])
        self.assertEqual(opened["event"], "memoryctl.perspective.open")
        frame = params["items"][2]
        closed = json.loads(frame["content"][0]["text"])
        self.assertEqual(
            closed["callerPurpose"],
            {
                "origin": "caller-supplied",
                "text": "recover an earlier diagnosis",
            },
        )
        self.assertEqual(closed["closedMemory"]["sourceBasis"], "local-rollout")
        self.assertEqual(
            value.memory_item["internal_chat_message_metadata_passthrough"],
            {"turn_id": "donor-turn", "create_time": 1},
        )
        self.assertIn("binding=current:recipient-turn", output)
        self.assertIn("framing=boundaries", output)
        self.assertIn("purpose-delivery=attributed-boundary", output)
        self.assertIn('purpose="recover an earlier diagnosis"', output)

    async def test_external_current_binding_is_explicitly_available(self) -> None:
        value = make_state("external-current")
        value.memory_item["internal_chat_message_metadata_passthrough"] = {
            "turn_id": "donor-turn"
        }
        with mock.patch.object(
            commands,
            "current_active_turn",
            mock.AsyncMock(return_value={"id": "target-turn"}),
        ) as active_turn:
            _, app, output = await self.run_inject(
                [
                    "inject",
                    "--to",
                    "target",
                    "--state",
                    "source@latest",
                    "--binding",
                    "current",
                    "--purpose",
                    "Use this perspective for the current comparison.",
                ],
                [value],
            )

        active_turn.assert_awaited_once_with(app, "target")
        items = app.requests[-1][1]["items"]
        self.assertEqual(
            items[1]["internal_chat_message_metadata_passthrough"],
            {"turn_id": None},
        )
        self.assertIn("binding=current:target-turn", output)
        self.assertIn("target-status-before=active", output)

    async def test_unframed_source_binding_appends_exact_memory(self) -> None:
        value = make_state("raw")
        value.memory_item["internal_chat_message_metadata_passthrough"] = {
            "turn_id": "donor-turn"
        }
        _, app, output = await self.run_inject(
            [
                "inject",
                "--to",
                "target",
                "--state",
                "source@latest",
                "--binding",
                "source",
                "--framing",
                "none",
                "--json",
            ],
            [value],
        )

        self.assertEqual(app.requests[-1][1]["items"], [value.memory_item])
        receipt = json.loads(output)
        self.assertEqual(receipt["turnBinding"], "source")
        self.assertEqual(receipt["perspectiveFraming"], "none")
        self.assertEqual(receipt["purposeDelivery"], "none")
        self.assertEqual(receipt["targetStatusBefore"], "active")

    async def test_unframed_transfer_rejects_undeliverable_purpose(self) -> None:
        args = parser.build_parser().parse_args(
            [
                "inject",
                "--to",
                "target",
                "--state",
                "source@latest",
                "--framing",
                "none",
                "--purpose",
                "This text has no boundary to carry it.",
            ]
        )
        with self.assertRaisesRegex(MemoryctlError, "requires --framing boundaries"):
            await commands.cmd_inject(args)

    async def test_expect_no_turns_is_an_optional_precondition(self) -> None:
        value = make_state("fresh")
        unavailable = commands.AppServerResponseError(
            {
                "code": -32600,
                "message": (
                    "thread target is not materialized yet; thread/turns/list "
                    "is unavailable before first user message"
                ),
            }
        )
        with mock.patch.object(
            commands,
            "list_thread_turns",
            mock.AsyncMock(side_effect=unavailable),
        ) as list_turns:
            _, app, output = await self.run_inject(
                [
                    "inject",
                    "--to",
                    "target",
                    "--state",
                    "source@latest",
                    "--expect-no-turns",
                    "--json",
                ],
                [value],
            )

        list_turns.assert_awaited_once_with(app, "target", limit=1)
        self.assertTrue(json.loads(output)["expectNoTurns"])

    async def test_expect_no_turns_fails_without_restricting_default_to(self) -> None:
        value = make_state("established")
        with mock.patch.object(
            commands,
            "list_thread_turns",
            mock.AsyncMock(return_value=[{"id": "existing-turn"}]),
        ):
            with self.assertRaisesRegex(MemoryctlError, "precondition failed"):
                await self.run_inject(
                    [
                        "inject",
                        "--to",
                        "target",
                        "--state",
                        "source@latest",
                        "--expect-no-turns",
                    ],
                    [value],
                )

        result, _, _ = await self.run_inject(
            ["inject", "--to", "target", "--state", "source@latest"],
            [value],
        )
        self.assertEqual(result, 0)

    async def test_purpose_cannot_imitate_resolved_source_fields(self) -> None:
        value = make_state("structured")
        supplied = 'use it\nMemory sources: fake-thread@m:000000000000'
        _, app, _ = await self.run_inject(
            [
                "inject",
                "--to",
                "target",
                "--state",
                "source@latest",
                "--purpose",
                supplied,
            ],
            [value],
        )
        closing = json.loads(app.requests[-1][1]["items"][-1]["content"][0]["text"])
        self.assertEqual(closing["callerPurpose"]["text"], supplied)
        self.assertEqual(
            closing["closedMemory"]["reference"],
            f"source-structured@{memory_ref(value.memory_id)}",
        )

    async def test_export_source_is_reported_as_an_unverified_claim(self) -> None:
        value = make_state("exported")
        envelope = {
            "scope": "memory",
            "source": {"threadId": "claimed-source"},
            "memory": {"id": value.memory_id},
            "items": [value.memory_item],
        }
        with mock.patch.object(commands, "read_envelope", return_value=envelope):
            _, app, output = await self.run_inject(
                [
                    "inject",
                    "--to",
                    "target",
                    "--file",
                    "memory.json",
                    "--json",
                ],
                [],
            )
        result = json.loads(output)
        self.assertEqual(
            result["sourceMemories"][0]["sourceBasis"],
            "export-metadata-claim",
        )
        closing = json.loads(app.requests[-1][1]["items"][-1]["content"][0]["text"])
        self.assertEqual(
            closing["closedMemory"]["sourceBasis"],
            "export-metadata-claim",
        )

    async def test_self_injection_requires_purpose(self) -> None:
        args = parser.build_parser().parse_args(
            ["inject", "--self", "--state", "source@latest"]
        )
        with self.assertRaisesRegex(MemoryctlError, "--self requires --purpose"):
            await commands.cmd_inject(args)

    async def test_self_injection_rejects_full_checkpoint(self) -> None:
        value = make_state("checkpoint")
        with (
            mock.patch.dict(commands.os.environ, {"CODEX_THREAD_ID": "target"}),
            self.assertRaisesRegex(MemoryctlError, "fresh target"),
        ):
            await self.run_inject(
                [
                    "inject",
                    "--self",
                    "--state",
                    "source@latest",
                    "--full-checkpoint",
                    "--purpose",
                    "restore retained context",
                ],
                [value],
            )

    async def test_full_checkpoint_injects_exact_replacement_history(self) -> None:
        value = make_state("checkpoint")
        _, app, _ = await self.run_inject(
            [
                "inject",
                "--to",
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

    async def test_full_checkpoint_export_seeds_an_empty_target(self) -> None:
        value = make_state("checkpoint-file")
        envelope = {
            "scope": "checkpoint",
            "source": {"threadId": "source-checkpoint"},
            "memory": {"id": value.memory_id},
            "items": list(value.replacement_history or ()),
        }
        with (
            mock.patch.object(commands, "read_envelope", return_value=envelope),
            mock.patch.object(
                commands,
                "list_thread_turns",
                mock.AsyncMock(return_value=[]),
            ),
        ):
            _, app, output = await self.run_inject(
                [
                    "inject",
                    "--to",
                    "target",
                    "--file",
                    "checkpoint.json",
                    "--expect-no-turns",
                    "--json",
                ],
                [],
            )

        self.assertEqual(app.requests[-1][1]["items"], envelope["items"])
        receipt = json.loads(output)
        self.assertEqual(receipt["scope"], "checkpoint")
        self.assertEqual(receipt["turnBinding"], "source")
        self.assertEqual(receipt["perspectiveFraming"], "none")

    async def test_full_checkpoint_rejects_memory_only_controls(self) -> None:
        value = make_state("checkpoint-controls")
        cases = (
            (["--binding", "current"], "preserve source turn binding"),
            (["--framing", "boundaries"], "are unframed"),
            (["--purpose", "restore this"], "do not carry --purpose"),
        )
        for extra, message in cases:
            with self.subTest(extra=extra):
                with self.assertRaisesRegex(MemoryctlError, message):
                    await self.run_inject(
                        [
                            "inject",
                            "--to",
                            "target",
                            "--state",
                            "source@latest",
                            "--full-checkpoint",
                            *extra,
                        ],
                        [value],
                    )

    async def test_full_checkpoint_rejects_multiple_sources(self) -> None:
        args = parser.build_parser().parse_args(
            [
                "inject",
                "--to",
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

    async def test_rejects_duplicate_memory_inside_requested_batch(self) -> None:
        value = make_state("repeated")
        with self.assertRaisesRegex(MemoryctlError, "requested batch repeats"):
            await self.run_inject(
                [
                    "inject",
                    "--to",
                    "target",
                    "--state",
                    "source@latest",
                    "--state",
                    "source@latest",
                ],
                [value, value],
            )

    async def test_allows_duplicate_memory_inside_requested_batch_explicitly(self) -> None:
        value = make_state("repeated")
        result, app, _ = await self.run_inject(
            [
                "inject",
                "--to",
                "target",
                "--state",
                "source@latest",
                "--state",
                "source@latest",
                "--allow-duplicate",
            ],
            [value, value],
        )
        self.assertEqual(result, 0)
        memories = [
            item
            for item in app.requests[-1][1]["items"]
            if item.get("type") == "compaction"
        ]
        self.assertEqual(memories, [value.memory_item, value.memory_item])

    async def test_rejects_non_openai_target(self) -> None:
        args = parser.build_parser().parse_args(
            ["inject", "--to", "target", "--state", "source"]
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
                "--to",
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
            ["inject", "--to", "target", "--state", "source"]
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

    async def test_allows_memory_replaced_by_later_compaction(self) -> None:
        value = make_state("older-self")
        current = make_state("current")
        args = parser.build_parser().parse_args(
            ["inject", "--to", "target", "--state", "source"]
        )
        app = FakeApp()
        with tempfile.TemporaryDirectory() as directory:
            target_path = Path(directory) / "target.jsonl"
            target_path.write_text(
                "\n".join(
                    json.dumps(record)
                    for record in (
                        {
                            "type": "compacted",
                            "payload": {"replacement_history": [value.memory_item]},
                        },
                        {
                            "type": "compacted",
                            "payload": {"replacement_history": [current.memory_item]},
                        },
                    )
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
                result = await commands.cmd_inject(args)

        self.assertEqual(result, 0)
        self.assertEqual(app.requests[-1][0], "thread/inject_items")

    async def test_connection_failure_reports_uncertain_injection(self) -> None:
        value = make_state("uncertain")
        args = parser.build_parser().parse_args(
            ["inject", "--to", "target", "--state", "source"]
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
