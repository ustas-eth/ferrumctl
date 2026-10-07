"""Opt-in persisted queue to real Codex delivery, without account credentials."""
import asyncio
import contextlib
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from codex_threadctl.appserver import create_thread, list_thread_turns
from codex_threadctl.config_input import read_config_file
from codex_wakectl import commands, parser, state


@unittest.skipUnless(os.environ.get("CODEX_THREADCTL_TEST_BINARY"), "opt-in real Codex binary")
class NativeDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_persisted_config_cold_loading_live_noop_and_goal_continuation(self):
        fixtures = str(Path(__file__).resolve().parents[2] / "codex-threadctl" / "tests")
        with mock.patch.object(sys, "path", [fixtures, *sys.path]):
            from test_config_native import MockModel, NativeServer

        class GatedModel(MockModel):
            def do_POST(self):
                if not self.server.gate.wait(10):
                    self.send_error(503, "fixture gate timed out")
                    return
                super().do_POST()

        backend = ThreadingHTTPServer(("127.0.0.1", 0), GatedModel)
        backend.requests = []
        backend.gate = threading.Event()
        backend.gate.set()
        serving = threading.Thread(target=backend.serve_forever, daemon=True)
        serving.start()
        try:
            with tempfile.TemporaryDirectory(prefix="wakectl-delivery-test-") as directory:
                home = Path(directory)
                (home / "config.toml").write_text(
                    'model = "gpt-6-luna"\nmodel_provider = "mock"\napproval_policy = "never"\n'
                    'default_permissions = ":read-only"\n[features]\ngoals = true\n'
                    '[skills.bundled]\nenabled = false\n'
                    '[model_providers.mock]\nname = "Local mock"\nwire_api = "responses"\n'
                    f'base_url = "http://127.0.0.1:{backend.server_port}"\n'
                )
                for name in ("alpha-smoke", "beta-smoke"):
                    path = home / "skills" / name / "SKILL.md"
                    path.parent.mkdir(parents=True)
                    path.write_text(f"---\nname: {name}\ndescription: Synthetic fixture.\n---\nFixture.\n")
                config_path = home / "worker.toml"
                config_path.write_text(
                    'model_reasoning_effort = "low"\ndefault_permissions = "worker"\n'
                    '[permissions.worker]\nextends = ":read-only"\n'
                    '[[skills.config]]\nname = "alpha-smoke"\nenabled = false\n'
                )
                config = read_config_file(str(config_path))
                queue = home / "jobs.sqlite3"
                async with NativeServer(home) as server:
                    target = (await create_thread(server, directory, config_overrides=config))["threadId"]
                    args = parser.build_parser().parse_args([
                        "add", "time", "--at", "2020-01-01T00:00:00Z", "--to", target,
                        "--resume", "--config-file", str(config_path), "--state", str(queue),
                    ])
                    with contextlib.redirect_stdout(io.StringIO()):
                        await commands.cmd_add(args)
                config_path.unlink()

                async def stopped(server, turn_id):
                    for _ in range(200):
                        turns = await list_thread_turns(server, target, limit=1)
                        if turns and turns[0]["id"] == turn_id and turns[0]["status"] == "completed":
                            return
                        await asyncio.sleep(0.05)
                    self.fail("mock turn did not complete")

                async def run_queue(server):
                    @contextlib.asynccontextmanager
                    async def attached(*args):
                        yield server

                    args = parser.build_parser().parse_args(["run", "--state", str(queue), "--json"])
                    with mock.patch.object(commands, "wakectl_appserver", attached), \
                         contextlib.redirect_stdout(io.StringIO()) as output:
                        self.assertEqual(await commands.cmd_run(args), 0, output.getvalue())
                    return json.loads(output.getvalue())["fired"][0]

                async with NativeServer(home) as server:
                    fired = await run_queue(server)
                    self.assertEqual(fired["delivery"], "resumedStarted")
                    self.assertTrue(fired["loading"]["configSubmitted"])
                    self.assertEqual(fired["loading"]["settings"]["activePermissionProfile"]["id"], "worker")
                    await stopped(server, fired["turnId"])
                    self.assertEqual(backend.requests[-1]["reasoning"]["effort"], "low")
                    catalogs = [str(item) for item in backend.requests[-1]["input"]
                                if item.get("role") == "developer" and "<skills_instructions>" in str(item)]
                    self.assertTrue(catalogs)
                    self.assertNotIn("alpha-smoke", catalogs[-1])
                    self.assertIn("beta-smoke", catalogs[-1])

                    # A different saved config must not reconfigure an already loaded worker.
                    config_path.write_text('model_reasoning_effort = "high"')
                    with contextlib.redirect_stdout(io.StringIO()):
                        await commands.cmd_add(args)
                    fired = await run_queue(server)
                    self.assertEqual(fired["loading"], {"outcome": "alreadyLoaded", "configSubmitted": False})
                    await stopped(server, fired["turnId"])
                    self.assertEqual(backend.requests[-1]["reasoning"]["effort"], "low")

                # Hold the resumed goal's model request to exercise active delivery deterministically.
                config_path.write_text('model_reasoning_effort = "low"\n'
                                       'default_permissions = "worker"\n'
                                       '[permissions.worker]\nextends = ":read-only"\n')
                with contextlib.redirect_stdout(io.StringIO()):
                    await commands.cmd_add(args)
                async with NativeServer(home) as server:
                    await server.request("thread/goal/set", {
                        "threadId": target, "objective": "Return OK.", "tokenBudget": 1,
                    })
                    backend.gate.clear()
                    try:
                        fired = await run_queue(server)
                        self.assertIn(fired["delivery"], {
                            "resumedActive", "resumedContinued", "eventNotifiedActive",
                        })
                        self.assertTrue(fired["loading"]["configSubmitted"])
                        self.assertNotIn("turn/start", [method for method, _ in server.calls])
                    finally:
                        backend.gate.set()
                    await stopped(server, fired["turnId"])
                self.assertEqual(len(state.list_jobs(queue, include_all=True)), 3)
        finally:
            backend.gate.set()
            await asyncio.to_thread(backend.shutdown)
            backend.server_close()
            serving.join()
