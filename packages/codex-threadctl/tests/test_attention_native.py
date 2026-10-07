"""Real Codex lifecycle + local model capture; no live server or credentials."""
import asyncio
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from codex_threadctl.appserver import create_thread, list_thread_turns
from codex_threadctl.attention import send_message, wake_with_resume
from test_config_native import MockModel, NativeServer


@unittest.skipUnless(os.environ.get("CODEX_THREADCTL_TEST_BINARY"), "opt-in real Codex binary")
class NativeAttentionTests(unittest.IsolatedAsyncioTestCase):
    async def test_agent_role_empty_wake_and_cold_loading(self):
        backend = ThreadingHTTPServer(("127.0.0.1", 0), MockModel)
        backend.requests = []
        serving = threading.Thread(target=backend.serve_forever, daemon=True)
        serving.start()
        try:
            with tempfile.TemporaryDirectory(prefix="threadctl-attention-test-") as directory:
                home = Path(directory)
                (home / "config.toml").write_text(
                    'model = "gpt-6-luna"\nmodel_provider = "mock"\napproval_policy = "never"\n'
                    'default_permissions = ":read-only"\n[features]\ngoals = true\n'
                    '[skills.bundled]\nenabled = false\n'
                    '[model_providers.mock]\nname = "Local mock"\nwire_api = "responses"\n'
                    f'base_url = "http://127.0.0.1:{backend.server_port}"\n'
                )
                async def stopped(server, target, turn_id):
                    for _ in range(200):
                        await list_thread_turns(server, target, limit=1)
                        for event in server.turn_notifications:
                            if (event.get("method") == "turn/completed"
                                and event["params"]["turn"]["id"] == turn_id):
                                self.assertEqual(event["params"]["turn"]["status"], "completed", event)
                                return
                        await asyncio.sleep(0.05)
                    self.fail("mock turn did not stop")

                async with NativeServer(home) as server:
                    target = (await create_thread(server, directory))["threadId"]
                    result = await send_message(server, target, "reviewer", "Direct peer report.")
                    self.assertEqual(result["messageOutcome"], "accepted")
                    self.assertEqual(backend.requests, [])
                    result = await send_message(server, target, "reviewer", "Please review this report.", wake=True)
                    self.assertEqual(result["wake"]["outcome"], "confirmedStarted")
                    await stopped(server, target, result["wake"]["turnId"])
                    # The native model request—not only a mocked RPC—retains agent provenance.
                    supplied = backend.requests[-1]["input"]
                    rendered = str(supplied)
                    self.assertIn("Direct peer report.", rendered)
                    self.assertIn("Please review this report.", rendered)
                    for item in supplied:
                        if "Direct peer report." in str(item) or "Please review this report." in str(item):
                            self.assertNotEqual(item.get("role"), "user", item)

                async with NativeServer(home) as server:
                    result = await wake_with_resume(server, target, {"model_reasoning_effort": "low"})
                    self.assertEqual(result["outcome"], "confirmedStarted")
                    self.assertTrue(result["loading"]["configSubmitted"])
                    await stopped(server, target, result["turnId"])
                    self.assertEqual(backend.requests[-1]["reasoning"]["effort"], "low")

                async with NativeServer(home) as server:
                    await server.request("thread/goal/set", {
                        "threadId": target, "objective": "Return OK.", "tokenBudget": 1,
                    })
                    result = await wake_with_resume(server, target)
                    self.assertEqual(result["outcome"], "confirmedResumed")
                    self.assertNotIn("turn/start", [method for method, _ in server.calls])
                    await stopped(server, target, result["turnId"])

                # Thread control also works on a server without the goals feature.
                config_path = home / "config.toml"
                config_path.write_text(config_path.read_text().replace("goals = true", "goals = false"))
                async with NativeServer(home) as server:
                    result = await wake_with_resume(server, target)
                    self.assertEqual(result["outcome"], "confirmedStarted")
                    await stopped(server, target, result["turnId"])
        finally:
            await asyncio.to_thread(backend.shutdown)
            backend.server_close()
            serving.join()
