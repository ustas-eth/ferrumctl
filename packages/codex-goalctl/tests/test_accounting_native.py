"""Real Codex accounting with gated local responses; no account or live server."""
import asyncio
import contextlib
import json
import os
import signal
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


async def stop_group(process):
    # Each fixture process owns a new session; never signal the caller's group.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        await asyncio.wait_for(process.wait(), 5)
    except TimeoutError:
        os.killpg(process.pid, signal.SIGKILL)
        await process.wait()


class GatedModel(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        number = self.server.request_count
        self.server.request_count += 1
        self.server.arrived[number].set()
        if not self.server.release[number].wait(15):
            self.send_error(504, "Synthetic response gate was not released")
            return
        response_id = f"r-{number}"
        events = [
            {"type": "response.created", "response": {"id": response_id}},
            {"type": "response.output_item.done", "item": {
                "type": "message", "id": f"m-{number}", "role": "assistant",
                "content": [{"type": "output_text", "text": "Synthetic result."}],
            }},
            {"type": "response.completed", "response": {
                "id": response_id, "usage": {
                    "input_tokens": 100, "input_tokens_details": {"cached_tokens": 40},
                    "output_tokens": 25, "total_tokens": 125,
                },
            }},
        ]
        data = "".join("data: " + json.dumps(event) + "\n\n" for event in events).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@unittest.skipUnless(os.environ.get("CODEX_GOALCTL_TEST_BINARY"), "opt-in real Codex binary")
class NativeGoalAccountingTests(unittest.IsolatedAsyncioTestCase):
    async def test_goal_transport_controls_live_accounting(self):
        # Test-only use of threadctl to create and observe the isolated worker.
        from codex_threadctl.appserver import AppServer, create_thread, list_thread_turns

        for case in (
            "standalone_before_wake", "endpoint_midturn", "endpoint_replace_midturn",
            "standalone_update_midturn", "endpoint_idle_continuation", "endpoint_repair_midturn",
            "auto_midturn", "auto_replace_midturn", "auto_idle_continuation",
            "standalone_midturn", "standalone_replace_midturn",
        ):
            with self.subTest(case=case):
                backend = ThreadingHTTPServer(("127.0.0.1", 0), GatedModel)
                backend.request_count = 0
                backend.arrived = [threading.Event() for _ in range(3)]
                backend.release = [threading.Event() for _ in range(3)]
                serving = threading.Thread(target=backend.serve_forever, daemon=True)
                serving.start()
                try:
                    async with contextlib.AsyncExitStack() as stack:
                        directory = stack.enter_context(tempfile.TemporaryDirectory(prefix="goalctl-accounting-test-"))
                        home = Path(directory)
                        (home / "config.toml").write_text(
                            'model = "gpt-6-luna"\nmodel_provider = "mock"\napproval_policy = "never"\n'
                            'default_permissions = ":read-only"\n[features]\ngoals = true\nplugins = false\n'
                            '[skills.bundled]\nenabled = false\n[model_providers.mock]\n'
                            'name = "Local mock"\nwire_api = "responses"\n'
                            f'base_url = "http://127.0.0.1:{backend.server_port}"\n'
                        )
                        socket = home / "app-server-control" / "app-server-control.sock"
                        socket.parent.mkdir()
                        endpoint = f"unix://{socket}"
                        env = os.environ | {"CODEX_HOME": directory}
                        env.pop("CODEX_GOALCTL_ENDPOINT", None)
                        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
                        with (home / "server.log").open("w") as log:
                            process = await asyncio.create_subprocess_exec(
                                os.environ["CODEX_GOALCTL_TEST_BINARY"], "app-server", "--listen", endpoint,
                                cwd=directory, env=env, stdout=log, stderr=log, start_new_session=True,
                            )
                            stack.push_async_callback(stop_group, process)
                            for _ in range(200):
                                if socket.exists():
                                    break
                                if process.returncode is not None:
                                    self.fail("isolated app-server exited before opening its socket")
                                await asyncio.sleep(0.02)
                            else:
                                self.fail("isolated app-server did not open its socket")

                            async def goal(operation, *arguments, live=False):
                                command = [sys.executable, "-m", "codex_goalctl.cli", operation, target,
                                           *arguments, "--json"]
                                if live is True:
                                    command += ["--endpoint", endpoint]
                                elif live is False:
                                    command += ["--standalone", "--codex-bin", os.environ["CODEX_GOALCTL_TEST_BINARY"]]
                                else:
                                    # Automatic selection must not attempt to launch this binary.
                                    command += ["--codex-bin", "/nonexistent-goalctl-test-codex"]
                                child = await asyncio.create_subprocess_exec(
                                    *command, cwd=directory, env=env,
                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                                    start_new_session=True,
                                )
                                try:
                                    stdout, stderr = await asyncio.wait_for(child.communicate(), 15)
                                finally:
                                    await stop_group(child)
                                self.assertEqual(child.returncode, 0, stderr.decode())
                                return json.loads(stdout)

                            async with AppServer(endpoint, 10) as app:
                                target = (await create_thread(app, directory))["threadId"]
                                if case in {"standalone_before_wake", "endpoint_replace_midturn", "standalone_update_midturn", "auto_replace_midturn", "standalone_replace_midturn"}:
                                    await goal("replace", "Initial synthetic objective.", "--token-budget", "1")
                                if case in {"endpoint_idle_continuation", "auto_idle_continuation"}:
                                    await goal("replace", "New synthetic objective.", "--token-budget", "1", live=None if case.startswith("auto_") else True)
                                else:
                                    await app.request("turn/start", {"threadId": target, "input": []})
                                self.assertTrue(await asyncio.to_thread(backend.arrived[0].wait, 10))
                                first_turn_id = (await list_thread_turns(app, target, limit=1))[0]["id"]
                                if case in {"endpoint_midturn", "endpoint_replace_midturn"}:
                                    await goal("replace", "New synthetic objective.", "--token-budget", "1", live=True)
                                elif case in {"auto_midturn", "auto_replace_midturn"}:
                                    await goal("replace", "New synthetic objective.", "--token-budget", "1", live=None)
                                elif case == "standalone_update_midturn":
                                    await goal("update", "--token-budget", "1")
                                elif case in {"standalone_midturn", "standalone_replace_midturn"}:
                                    await goal("replace", "New synthetic objective.", "--token-budget", "1")
                                elif case == "endpoint_repair_midturn":
                                    previous = (await goal("replace", "New synthetic objective.", "--token-budget", "1"))["goal"]
                                    repaired = (await goal("update", "--status", "active", live=True))["goal"]
                                    self.assertEqual(repaired["createdAt"], previous["createdAt"])
                                    self.assertEqual(repaired["tokensUsed"], previous["tokensUsed"])
                                backend.release[0].set()
                                for _ in range(200):
                                    turns = await list_thread_turns(app, target, limit=2)
                                    if any(turn["id"] == first_turn_id and turn["status"] == "completed" for turn in turns):
                                        break
                                    await asyncio.sleep(0.02)
                                else:
                                    self.fail("synthetic first turn did not complete")
                                observed = (await goal("get", live=True))["goal"]
                                expected_requests = 1
                                if case in {"standalone_midturn", "standalone_replace_midturn"}:
                                    # Persisted-only writes do not rebind another server's turn.
                                    self.assertEqual(observed["tokensUsed"], 0, observed)
                                    self.assertEqual(observed["status"], "active", observed)
                                    # Codex can pick up persisted state at the turn boundary.
                                    self.assertTrue(await asyncio.to_thread(backend.arrived[1].wait, 10))
                                    backend.release[1].set()
                                    for _ in range(200):
                                        observed = (await goal("get", live=True))["goal"]
                                        if observed["status"] == "budgetLimited":
                                            break
                                        await asyncio.sleep(0.02)
                                    expected_requests = 2
                                self.assertEqual(observed["tokensUsed"], 85, observed)
                                self.assertEqual(observed["status"], "budgetLimited", observed)
                                self.assertEqual(backend.request_count, expected_requests)
                                if case == "standalone_update_midturn":
                                    updated = (await goal("update", "--status", "paused", "--token-budget", "150", live=True))["goal"]
                                    self.assertEqual(updated["tokensUsed"], 85)
                                    self.assertEqual(updated["createdAt"], observed["createdAt"])
                                    await goal("update", "--status", "active", live=True)
                                    self.assertTrue(await asyncio.to_thread(backend.arrived[1].wait, 10))
                                    backend.release[1].set()
                                    for _ in range(200):
                                        final = (await goal("get", live=True))["goal"]
                                        if final["status"] == "budgetLimited":
                                            break
                                        await asyncio.sleep(0.02)
                                    self.assertEqual(final["tokensUsed"], 170, final)
                                    self.assertEqual(final["status"], "budgetLimited", final)
                                    self.assertEqual(backend.request_count, 2)
                                await goal("clear", live=True)
                finally:
                    for gate in backend.release:
                        gate.set()
                    await asyncio.to_thread(backend.shutdown)
                    backend.server_close()
                    serving.join()
