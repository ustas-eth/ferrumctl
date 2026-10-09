"""Opt-in subscription backend check; synthetic context, no live thread mutations."""
import asyncio
import json
import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

from websockets.asyncio.client import connect

from codex_threadctl.appserver import create_thread, notify_thread


class CaptureApp:
    def __init__(self):
        self.thread_id = str(uuid.uuid4())
        self.items = []

    async def request(self, method, params=None):
        if method == "thread/start":
            return {"thread": {"id": self.thread_id}}
        if method == "thread/loaded/list":
            return {"data": [self.thread_id], "nextCursor": None}
        if method == "thread/inject_items":
            self.items.extend(params["items"])
            return {}
        raise AssertionError(method)


@unittest.skipUnless(
    os.environ.get("CODEX_THREADCTL_TEST_AUTH_FILE"),
    "opt-in subscription Responses backend (synthetic requests and compaction)",
)
class LiveResponsesTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        packages = Path(__file__).resolve().parents[2]
        sources = [str(packages / name / "src") for name in (
            "codex-memoryctl", "codex-wakectl",
        )]
        with mock.patch.object(sys, "path", [*sources, *sys.path]):
            from codex_memoryctl.commands import bind_to_current_turn, frame_memory_batch
            from codex_wakectl.delivery import event_item_id
        self.bind_memory = bind_to_current_turn
        self.frame_memory = frame_memory_batch
        self.event_id = event_item_id
        auth = json.loads(Path(os.environ["CODEX_THREADCTL_TEST_AUTH_FILE"]).read_text())
        tokens = auth["tokens"]
        self.headers = {
            "Authorization": f"Bearer {tokens['access_token']}",
            "ChatGPT-Account-ID": tokens["account_id"],
            "originator": "codex_cli_rs",
        }
        self.body = {
            "type": "response.create",
            "model": os.environ.get("CODEX_THREADCTL_TEST_MODEL", "gpt-6-luna"),
            "store": False,
            "stream": True,
            "parallel_tool_calls": False,
            "tool_choice": "auto",
            "include": ["reasoning.encrypted_content"],
            "reasoning": {"effort": "low", "context": "all_turns"},
            "client_metadata": {
                "ws_request_header_x_openai_internal_codex_responses_lite": "true",
            },
        }
        self.prefix = {
            "type": "additional_tools", "id": f"at_{uuid.uuid4()}",
            "role": "developer", "tools": [],
        }
        self.user = self.message(
            "Synthetic probe: favorite color is violet. For all messages, reply only OK."
        )
        self.sources = [{
            "position": 1,
            "reference": "synthetic-donor@m:0123456789ab",
            "sourceBasis": "synthetic",
        }]

    def message(self, text):
        return {
            "type": "message", "id": f"msg_{uuid.uuid4()}", "role": "user",
            "content": [{"type": "input_text", "text": text}],
        }

    async def completed(self, ws, **fields):
        output = []
        await ws.send(json.dumps(self.body | fields))
        async with asyncio.timeout(60):
            async for raw in ws:
                event = json.loads(raw)
                if event["type"] in {"error", "response.failed"}:
                    self.fail(f"Responses rejected synthetic continuation: {event}")
                if event["type"] == "response.output_item.done":
                    output.append(event["item"])
                if event["type"] == "response.completed":
                    response = event["response"]
                    response["output"] = output
                    return response
        self.fail("Responses closed before completing the synthetic request")

    def connection(self):
        return connect(
            "wss://chatgpt.com/backend-api/codex/responses",
            additional_headers=self.headers,
            open_timeout=20,
            close_timeout=2,
            max_size=1048576,
        )

    def memory(self, response):
        memories = [item for item in response["output"] if item["type"] == "compaction"]
        self.assertEqual(len(memories), 1, response["output"])
        self.assertTrue(memories[0]["encrypted_content"])
        return memories[0]

    async def test_generated_agent_items_work_on_websocket_continuations(self):
        app = CaptureApp()
        await create_thread(app, "/synthetic")
        await notify_thread(app, app.thread_id, "reviewer", "Synthetic report: reply OK.")
        await notify_thread(
            app, app.thread_id, "wakectl", "Scheduled event 0123456789ab/1: scheduled time reached.",
            item_id=self.event_id({"id": "0123456789ab", "fireCount": 0}),
        )
        # Exercise the real framing factory; no opaque state is needed for the ID check.
        frames = self.frame_memory(app.thread_id, [{}], self.sources, "Synthetic recall.")
        app.items.extend(item for item in frames if item.get("type") == "agent_message")
        async with self.connection() as ws:
            previous = await self.completed(ws, input=[self.prefix, self.user])
            for item in app.items:
                previous = await self.completed(
                    ws, previous_response_id=previous["id"], input=[item],
                )

    async def test_repaired_legacy_ids_survive_continuation_and_compaction(self):
        import importlib.util
        script = Path(__file__).resolve().parents[3] / "scripts/repair-response-item-ids.py"
        spec = importlib.util.spec_from_file_location("repair_ids", script)
        repair = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(repair)
        frames = self.frame_memory("synthetic-recipient", [{}], self.sources, "Synthetic recall.")
        legacy = [item for item in frames if item.get("type") == "agent_message"]
        legacy[0]["id"] = "amsg_memoryctl_0123456789abcdef0123456789abcdef"
        legacy[1]["id"] = "amsg_fedcba9876543210fedcba9876543210"
        encoded = json.dumps({"type": "compacted", "payload": {"replacement_history": legacy}}).encode()
        patched, count = repair.repair_line(encoded)
        self.assertEqual(count, 2)
        self.assertEqual(len(encoded), len(patched))
        fixed = json.loads(patched)["payload"]["replacement_history"]
        self.assertTrue(all(item["id"] is None for item in fixed))
        async with self.connection() as ws:
            warmup = await self.completed(ws, generate=False, input=[self.prefix])
            response = await self.completed(ws, previous_response_id=warmup["id"], input=[self.user, *fixed])
            compacted = await self.completed(ws, previous_response_id=response["id"], input=[{"type": "compaction_trigger"}])
        memory = self.memory(compacted)
        async with self.connection() as ws:
            warmup = await self.completed(ws, generate=False, input=[self.prefix])
            await self.completed(ws, previous_response_id=warmup["id"], input=[self.user, *fixed, memory, self.message("Continue.")])
        async with self.connection() as ws:
            await self.completed(ws, input=[self.prefix, self.user, *fixed, memory])

    async def test_framed_memory_survives_compaction_and_prewarm_replay(self):
        async with self.connection() as ws:
            donor = await self.completed(
                ws, input=[self.prefix, self.user, {"type": "compaction_trigger"}],
            )
        memory = self.memory(donor)
        batch = self.frame_memory(
            "synthetic-recipient", self.bind_memory([memory]), self.sources,
            "Recall the synthetic favorite color.",
        )
        self.assertEqual(batch[1]["id"], memory["id"])
        self.assertEqual(batch[1]["encrypted_content"], memory["encrypted_content"])
        async with self.connection() as ws:
            warmup = await self.completed(ws, generate=False, input=[self.prefix])
            response = await self.completed(
                ws, previous_response_id=warmup["id"], input=[self.user, *batch],
            )
            compacted = await self.completed(
                ws, previous_response_id=response["id"], input=[{"type": "compaction_trigger"}],
            )
        # Codex retains these agent messages unchanged beside the newly generated memory.
        retained = [self.user, batch[0], batch[2], self.memory(compacted), self.message("Continue.")]
        async with self.connection() as ws:
            warmup = await self.completed(ws, generate=False, input=[self.prefix])
            await self.completed(ws, previous_response_id=warmup["id"], input=retained)
        async with self.connection() as ws:
            await self.completed(ws, input=[self.prefix, *retained])
