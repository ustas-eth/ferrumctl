"""Real restart recovery with a local model; no credentials or live server."""
import asyncio
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from codex_threadctl.appserver import create_thread
from codex_threadctl.config_input import read_config_file
from codex_threadctl.configuration import configure_thread, resume_thread
from codex_threadctl.errors import AppServerResponseError, ThreadStateError, error_record
from codex_threadctl.recovery import read_recovery, write_recovery
from test_config_native import MockModel, NativeServer


@unittest.skipUnless(os.environ.get("CODEX_THREADCTL_TEST_BINARY"), "opt-in real Codex binary")
class NativeRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_saved_profile_definition_requires_a_cold_load(self):
        with tempfile.TemporaryDirectory(prefix="threadctl-profile-boundary-") as directory:
            home = Path(directory)
            state = home / "recovery.sqlite3"
            (home / "config.toml").write_text(
                'model="gpt-6-luna"\nmodel_provider="mock"\napproval_policy="never"\n'
                'default_permissions=":read-only"\n[skills.bundled]\nenabled=false\n'
                '[model_providers.mock]\nname="Unused local mock"\nwire_api="responses"\n'
                'base_url="http://127.0.0.1:9"\n'
            )
            definition = {"permissions": {"worker": {"extends": ":read-only"}}}
            async with NativeServer(home) as server:
                target = (await create_thread(server, directory))["threadId"]
                with self.assertRaises(AppServerResponseError) as caught:
                    await configure_thread(server, target, permission_profile="worker")
                self.assertIn("default_permissions", str(caught.exception))
                self.assertEqual(error_record(caught.exception)["method"], "thread/settings/update")

                write_recovery(state, server.endpoint, target, definition)
                record = read_recovery(state, server.endpoint, target)
                with self.assertRaisesRegex(ThreadStateError, "only on cold loading"):
                    await resume_thread(
                        server, target, continue_goal=True,
                        config_overrides=definition, recovery_state=state,
                    )
                # Saving a definition changes neither the loaded thread nor native selection.
                with self.assertRaises(AppServerResponseError):
                    await configure_thread(server, target, permission_profile="worker")
                self.assertEqual(read_recovery(state, server.endpoint, target), record)
                self.assertNotIn("thread/resume", [method for method, _ in server.calls])
                self.assertNotIn("turn/start", [method for method, _ in server.calls])

            async with NativeServer(home) as server:
                loaded = await resume_thread(
                    server, target, continue_goal=True,
                    permission_profile="worker", recovery_state=state,
                )
                self.assertEqual(loaded["settings"]["activePermissionProfile"]["id"], "worker")
                self.assertEqual(loaded["recovery"]["submittedKeys"], ["permissions"])
                self.assertEqual((await configure_thread(
                    server, target, permission_profile="worker",
                ))["outcome"], "accepted")
                self.assertNotIn("turn/start", [method for method, _ in server.calls])

    async def test_restart_preserves_skills_and_native_changes_without_source_file(self):
        backend = ThreadingHTTPServer(("127.0.0.1", 0), MockModel)
        backend.requests = []
        serving = threading.Thread(target=backend.serve_forever, daemon=True)
        serving.start()
        try:
            with tempfile.TemporaryDirectory(prefix="threadctl-remembered-native-") as directory:
                home = Path(directory)
                state = home / "recovery.sqlite3"
                (home / "config.toml").write_text(
                    'model="gpt-6-sol"\nmodel_provider="mock"\nmodel_reasoning_effort="low"\n'
                    'approval_policy="never"\ndefault_permissions=":read-only"\n'
                    '[skills.bundled]\nenabled=false\n[model_providers.mock]\n'
                    'name="Local mock"\nwire_api="responses"\n'
                    f'base_url="http://127.0.0.1:{backend.server_port}"\n'
                )
                for name in ("alpha-smoke", "beta-smoke"):
                    path = home / "skills" / name / "SKILL.md"
                    path.parent.mkdir(parents=True)
                    path.write_text(f"---\nname: {name}\ndescription: Synthetic fixture.\n---\nFixture.\n")
                config_file = home / "worker.toml"
                config_file.write_text('model_context_window=120000\n'
                                       '[permissions.worker]\nextends=":read-only"\n'
                                       '[[skills.config]]\nname="alpha-smoke"\nenabled=false\n')
                async with NativeServer(home) as server:
                    created = await create_thread(
                        server, directory, model="gpt-6-luna", effort="high",
                        permission_profile="worker", config_overrides=read_config_file(str(config_file)),
                        recovery_state=state,
                    )
                    target = created["threadId"]
                    self.assertEqual(created["recovery"]["keys"],
                                     ["model_context_window", "permissions", "skills"])
                config_file.unlink()

                async with NativeServer(home) as server:
                    # Cold recovery before the first model turn also restores native choices.
                    resumed = await resume_thread(server, target, continue_goal=True, recovery_state=state)
                    self.assertEqual(resumed["settings"]["model"], "gpt-6-luna")
                    self.assertEqual(resumed["settings"]["reasoningEffort"], "high")
                    self.assertEqual(resumed["settings"]["activePermissionProfile"]["id"], "worker")
                    await server.turn(target)
                    # Simulate another native client changing selections, without a new turn.
                    await configure_thread(server, target, model="gpt-6-sol", effort="low",
                                           permission_profile=":workspace", approval_policy="never")

                async with NativeServer(home) as server:
                    resumed = await resume_thread(server, target, continue_goal=True, recovery_state=state)
                    self.assertEqual(resumed["settings"]["model"], "gpt-6-sol")
                    self.assertEqual(resumed["settings"]["reasoningEffort"], "low")
                    self.assertEqual(resumed["settings"]["activePermissionProfile"]["id"], ":workspace")
                    params = next(params for method, params in server.calls if method == "thread/resume")
                    self.assertEqual(params["config"]["model_context_window"], 120000)
                    self.assertNotIn("model", params["config"])
                    self.assertNotIn("default_permissions", params["config"])
                    await server.turn(target)
                    self.assertEqual(backend.requests[-1]["model"], "gpt-6-sol")
                    self.assertEqual(backend.requests[-1]["reasoning"]["effort"], "low")
                    catalogs = [str(item) for item in backend.requests[-1]["input"]
                                if item.get("role") == "developer" and "<skills_instructions>" in str(item)]
                    self.assertNotIn("alpha-smoke", catalogs[-1])
                    self.assertIn("beta-smoke", catalogs[-1])
                    self.assertEqual(read_recovery(state, server.endpoint, target)["config"], params["config"])
        finally:
            await asyncio.to_thread(backend.shutdown)
            backend.server_close()
            serving.join()
