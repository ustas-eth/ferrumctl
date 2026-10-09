"""Validate byte-preserving repair against native paginated and inherited history."""

import asyncio
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

from test_config_native import MockModel, NativeServer


@unittest.skipUnless(os.environ.get("CODEX_THREADCTL_TEST_BINARY"), "opt-in real Codex binary")
class NativeRepairTests(unittest.IsolatedAsyncioTestCase):
    async def test_paginated_fork_and_context_remain_readable_after_repair(self):
        spec = importlib.util.spec_from_file_location(
            "repair_ids", Path(__file__).resolve().parents[3] / "scripts/repair-response-item-ids.py"
        )
        repair = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(repair)
        backend = ThreadingHTTPServer(("127.0.0.1", 0), MockModel)
        backend.requests = []
        serving = threading.Thread(target=backend.serve_forever, daemon=True)
        serving.start()
        try:
            with tempfile.TemporaryDirectory(prefix="threadctl-repair-test-") as directory:
                root = Path(directory)
                home = root / "home"
                home.mkdir()
                (home / "config.toml").write_text(
                    'model = "gpt-6-luna"\nmodel_provider = "mock"\napproval_policy = "never"\n'
                    'default_permissions = ":read-only"\n[skills.bundled]\nenabled = false\n'
                    '[model_providers.mock]\nname = "Local mock"\nwire_api = "responses"\n'
                    f'base_url = "http://127.0.0.1:{backend.server_port}"\n'
                )
                async with NativeServer(home) as server:
                    created = await server.request("thread/start", {"cwd": str(home), "historyMode": "paginated"})
                    target = created["thread"]["id"]
                    await server.request("thread/inject_items", {"threadId": target, "items": [{
                        "type": "agent_message", "id": "amsg_memoryctl_0123456789abcdef0123456789abcdef",
                        "author": "memoryctl", "recipient": target,
                        "content": [{"type": "input_text", "text": "Synthetic retained report."}],
                    }]})
                    await server.turn(target)
                    self.assertIn("Synthetic retained report.", str(backend.requests[-1]))
                    fork = (await server.request("thread/fork", {"threadId": target}))["thread"]["id"]
                paths = list((home / "sessions").rglob("*.jsonl"))
                before = {path: [len(row) for row in path.read_bytes().splitlines(keepends=True)] for path in paths}
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    code = repair.main(["--codex-home", str(home), "--apply", "--backup-dir", str(root / "backup")])
                self.assertEqual(code, 0, output.getvalue())
                self.assertGreater(json.loads(output.getvalue())["repairedFiles"], 0)
                for path in paths:
                    self.assertEqual(before[path], [len(row) for row in path.read_bytes().splitlines(keepends=True)])
                async with NativeServer(home) as server:
                    for thread_id in (target, fork):
                        await server.request("thread/resume", {"threadId": thread_id, "skipHistory": True})
                        turns = await server.request("thread/turns/list", {"threadId": thread_id, "limit": 5})
                        self.assertTrue(turns["data"])
                        await server.turn(thread_id)
                        items = backend.requests[-1]["input"]
                        retained = [item for item in items if item.get("type") == "agent_message"]
                        self.assertTrue(any("Synthetic retained report." in str(item) for item in retained))
                        self.assertTrue(all(item.get("id") is None or "memoryctl_" not in item["id"] for item in retained))
        finally:
            await asyncio.to_thread(backend.shutdown)
            backend.server_close()
            serving.join()
