"""Opt-in subscription backend check; synthetic context, no live thread mutations."""
import asyncio
import json
import os
import unittest
import uuid
from pathlib import Path

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
    "opt-in subscription Responses backend (three small model requests)",
)
class LiveResponsesTests(unittest.IsolatedAsyncioTestCase):
    async def test_generated_agent_ids_work_on_websocket_continuations(self):
        auth = json.loads(Path(os.environ["CODEX_THREADCTL_TEST_AUTH_FILE"]).read_text())
        tokens = auth["tokens"]
        headers = {
            "Authorization": f"Bearer {tokens['access_token']}",
            "ChatGPT-Account-ID": tokens["account_id"],
            "originator": "codex_cli_rs",
        }
        app = CaptureApp()
        await create_thread(app, "/synthetic")
        await notify_thread(app, app.thread_id, "reviewer", "Synthetic report: reply OK.")
        body = {
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

        async def completed(ws, request):
            await ws.send(json.dumps(request))
            async with asyncio.timeout(45):
                async for raw in ws:
                    event = json.loads(raw)
                    if event["type"] in {"error", "response.failed"}:
                        self.fail(f"Responses rejected synthetic continuation: {event}")
                    if event["type"] == "response.completed":
                        return event["response"]["id"]
            self.fail("Responses closed before completing the synthetic request")

        async with connect(
            "wss://chatgpt.com/backend-api/codex/responses",
            additional_headers=headers,
            open_timeout=20,
            close_timeout=2,
            max_size=1048576,
        ) as ws:
            previous = await completed(ws, body | {"input": [
                {"type": "additional_tools", "id": f"at_{uuid.uuid4()}",
                 "role": "developer", "tools": []},
                {"type": "message", "id": f"msg_{uuid.uuid4()}", "role": "user",
                 "content": [{"type": "input_text", "text": "Synthetic probe. Reply OK."}]},
            ]})
            for item in app.items:
                previous = await completed(ws, body | {
                    "previous_response_id": previous, "input": [item],
                })
