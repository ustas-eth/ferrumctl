"""Recovery state and native-operation boundaries, all in temporary stores."""
import io
import json
import os
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from codex_threadctl import appserver, attention, cli, configuration, parser, recovery
from codex_threadctl.errors import AppServerResponseError, OperationError, ThreadctlError, ThreadStateError
from test_appserver import FakeApp


class RecoveryStoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="threadctl-recovery-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.state = self.root / "records.sqlite3"

    def test_absent_read_and_show_create_nothing(self):
        self.assertIsNone(recovery.read_recovery(self.state, "unix:///a", "thread"))
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.main(["recovery", "thread", "--state", str(self.state),
                                       "--endpoint", "unix:///a", "--json"]), 0)
        self.assertEqual(json.loads(output.getvalue())["outcome"], "notFound")
        self.assertFalse(self.state.exists())

    def test_endpoint_and_thread_identity_are_independent(self):
        recovery.write_recovery(self.state, "unix:///a", "thread", {"model_context_window": 120000})
        self.assertIsNone(recovery.read_recovery(self.state, "unix:///b", "thread"))
        self.assertIsNone(recovery.read_recovery(self.state, "unix:///a", "other"))
        self.assertEqual(recovery.read_recovery(self.state, "unix:///a", "thread")["config"],
                         {"model_context_window": 120000})

    def test_native_selections_are_never_saved(self):
        result = recovery.write_recovery(self.state, "unix:///a", "thread", {
            "model": "old", "model_provider": "old", "model_reasoning_effort": "low",
            "approval_policy": "never", "default_permissions": "worker",
            "sandbox_mode": "danger-full-access", "cwd": "/old",
            "permissions": {"worker": {"extends": ":read-only"}},
        })
        self.assertEqual(result["keys"], ["permissions"])
        self.assertEqual(recovery.read_recovery(self.state, "unix:///a", "thread")["config"],
                         {"permissions": {"worker": {"extends": ":read-only"}}})

    def test_inline_credentials_rejected_without_echo_or_state(self):
        for config in ({"model_providers": {"custom": {"experimental_bearer_token": "fixture-private"}}},
                       {"mcp_servers": {"service": {"http_headers": {"Authorization": "fixture-private"}}}}):
            with self.assertRaises(ThreadctlError) as caught:
                recovery.write_recovery(self.state, "unix:///a", "thread", config)
            self.assertNotIn("fixture-private", str(caught.exception))
        self.assertFalse(self.state.exists())
        self.assertEqual(recovery.recovery_config({"model_providers": {"custom": {
            "env_key": "CUSTOM_KEY", "env_http_headers": {"Authorization": "SERVICE_KEY"},
        }}})["model_providers"]["custom"]["env_key"], "CUSTOM_KEY")

    def test_default_private_modes_and_custom_existing_modes(self):
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(self.root)}):
            path = recovery.default_state_path()
            recovery.write_recovery(path, "unix:///a", "thread", {"model_context_window": 120000})
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        recovery.write_recovery(self.state, "unix:///a", "thread", {"model_context_window": 120000})
        self.state.chmod(0o640)
        recovery.write_recovery(self.state, "unix:///a", "other", {"model_context_window": 130000})
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o640)

    def test_concurrent_different_workers_and_stale_update(self):
        recovery.write_recovery(self.state, "unix:///a", "seed", {"model_context_window": 100000})
        def save(index):
            recovery.write_recovery(self.state, "unix:///a", str(index), {"model_context_window": index})
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(save, range(16)))
        for index in range(16):
            self.assertEqual(recovery.read_recovery(self.state, "unix:///a", str(index))["config"],
                             {"model_context_window": index})
        prior = recovery.read_recovery(self.state, "unix:///a", "seed")
        recovery.write_recovery(self.state, "unix:///a", "seed", {"model_context_window": 200000})
        with self.assertRaisesRegex(ThreadctlError, "changed during loading"):
            recovery.write_recovery(self.state, "unix:///a", "seed", {"model_context_window": 150000},
                                    expected_revision=prior["revision"])
        self.assertEqual(recovery.read_recovery(self.state, "unix:///a", "seed")["config"],
                         {"model_context_window": 200000})

    def test_cli_replace_values_and_forget_work_offline(self):
        config = self.root / "worker.toml"
        config.write_text('model="gpt-6-luna"\nmodel_context_window=120000\n')
        base = ["recovery", "thread", "--endpoint", "ws://example.invalid:1234",
                "--state", str(self.state), "--json"]
        with mock.patch.object(appserver, "connect_websocket") as connect:
            for options in (["--config-file", str(config)], [], ["--values"], ["--forget"], []):
                with redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(cli.main(base + options), 0)
                result = json.loads(output.getvalue())
                if options == ["--values"]:
                    self.assertEqual(result["config"], {"model_context_window": 120000})
                else:
                    self.assertNotIn("config", result)
            connect.assert_not_called()
        self.assertEqual(result["outcome"], "notFound")

    def test_corrupt_record_is_visible_failure_but_can_be_forgotten(self):
        recovery.write_recovery(self.state, "unix:///a", "thread", {"model_context_window": 1})
        with sqlite3.connect(self.state) as connection:
            connection.execute("UPDATE recovery_settings SET config_json='[]'")
        with self.assertRaises(ThreadctlError):
            recovery.read_recovery(self.state, "unix:///a", "thread")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["recovery", "thread", "--forget", "--state", str(self.state),
                                       "--endpoint", "unix:///a"]), 0)
        self.assertIsNone(recovery.read_recovery(self.state, "unix:///a", "thread"))


class RecoveryOperationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="threadctl-recovery-operation-")
        self.addCleanup(temporary.cleanup)
        self.state = Path(temporary.name) / "recovery.sqlite3"
        self.app = FakeApp(loaded=False)
        self.app.endpoint = "unix:///synthetic/control.sock"

    def save(self, config):
        recovery.write_recovery(self.state, self.app.endpoint, "thread", config)

    async def test_create_saves_config_but_not_server_defaults(self):
        self.app.request = mock.AsyncMock(side_effect=[{"thread": {"id": "created"}}, {}])
        await appserver.create_thread(self.app, "/project", model="new", effort="high",
                                     config_overrides={"model": "old", "model_context_window": 120000},
                                     recovery_state=self.state)
        self.assertEqual(recovery.read_recovery(self.state, self.app.endpoint, "created")["config"],
                         {"model_context_window": 120000})

    async def test_create_storage_failure_happens_before_submission(self):
        self.app.request = mock.AsyncMock()
        with mock.patch.object(appserver, "database", side_effect=ThreadctlError("storage unavailable")):
            with self.assertRaises(ThreadctlError):
                await appserver.create_thread(self.app, "/project", recovery_state=self.state,
                                             config_overrides={"model_context_window": 120000})
        self.app.request.assert_not_awaited()

    async def test_create_save_failure_preserves_created_thread_id(self):
        self.app.request = mock.AsyncMock(return_value={"thread": {"id": "created"}})
        with mock.patch.object(recovery, "write_recovery", side_effect=ThreadctlError("disk full")):
            with self.assertRaises(OperationError) as caught:
                await appserver.create_thread(self.app, "/project", recovery_state=self.state,
                                             config_overrides={"model_context_window": 120000})
        self.assertEqual(caught.exception.result["threadId"], "created")
        self.assertEqual(caught.exception.result["outcome"], "partial")
        self.assertEqual(self.app.request.await_count, 2)

    async def test_resume_reuses_supplementary_settings_in_loading_request(self):
        self.save({"skills": {"include_instructions": False}, "model_context_window": 120000})
        result = await configuration.resume_thread(self.app, "thread", continue_goal=True,
                                                   recovery_state=self.state)
        self.assertEqual(self.app.calls[-1], ("thread/resume", {
            "threadId": "thread", "excludeTurns": True,
            "config": {"skills": {"include_instructions": False}, "model_context_window": 120000},
        }))
        self.assertEqual(result["recovery"]["outcome"], "submitted")

    async def test_explicit_file_replaces_top_level_value_and_updates_record(self):
        self.save({"skills": {"include_instructions": False}, "model_context_window": 120000})
        await configuration.resume_thread(self.app, "thread", continue_goal=True,
                                          recovery_state=self.state,
                                          config_overrides={"skills": {"config": []}})
        self.assertEqual(recovery.read_recovery(self.state, self.app.endpoint, "thread")["config"],
                         {"skills": {"config": []}, "model_context_window": 120000})

    async def test_scheduled_snapshot_is_not_a_registry_update(self):
        self.save({"model_context_window": 120000})
        await configuration.resume_thread(self.app, "thread", continue_goal=True,
                                          recovery_state=self.state, remember_config=False,
                                          config_overrides={"model_context_window": 130000})
        self.assertEqual(self.app.calls[-1][1]["config"]["model_context_window"], 130000)
        self.assertEqual(recovery.read_recovery(self.state, self.app.endpoint, "thread")["config"],
                         {"model_context_window": 120000})

    async def test_unsaved_job_snapshot_keeps_native_config_compatibility(self):
        self.save({"model_context_window": 120000})
        snapshot = {"model_providers": {"custom": {"experimental_bearer_token": "fixture-private"}}}
        await configuration.resume_thread(self.app, "thread", continue_goal=True,
                                          recovery_state=self.state, remember_config=False,
                                          config_overrides=snapshot)
        self.assertEqual(self.app.calls[-1][1]["config"], {"model_context_window": 120000, **snapshot})
        self.assertEqual(recovery.read_recovery(self.state, self.app.endpoint, "thread")["config"],
                         {"model_context_window": 120000})

    async def test_bypass_keeps_direct_config_and_leaves_record_untouched(self):
        self.save({"model_context_window": 120000})
        await configuration.resume_thread(self.app, "thread", continue_goal=True,
                                          config_overrides={"model_context_window": 130000})
        self.assertEqual(self.app.calls[-1][1]["config"], {"model_context_window": 130000})
        self.assertEqual(recovery.read_recovery(self.state, self.app.endpoint, "thread")["config"],
                         {"model_context_window": 120000})

    async def test_loaded_attention_never_reads_store_or_reconfigures(self):
        self.app.loaded = True
        with mock.patch.object(configuration, "read_recovery", side_effect=AssertionError("read")):
            result = await attention.load_for_attention(self.app, "thread", None, recovery_state=self.state)
        self.assertEqual(result, {"outcome": "alreadyLoaded", "configSubmitted": False})
        self.assertEqual([method for method, _ in self.app.calls], ["thread/loaded/list"])

    async def test_loaded_load_does_not_replay_record(self):
        self.app.loaded = True
        with mock.patch.object(configuration, "read_recovery", side_effect=AssertionError("read")):
            await configuration.resume_thread(self.app, "thread", continue_goal=True, recovery_state=self.state)
        self.assertNotIn("config", self.app.calls[-1][1])

    async def test_warm_config_file_rejection_explains_boundaries_without_mutation(self):
        self.app.loaded = True
        self.save({"model_context_window": 120000})
        before = recovery.read_recovery(self.state, self.app.endpoint, "thread")
        with self.assertRaises(ThreadStateError) as caught:
            await configuration.resume_thread(
                self.app, "thread", continue_goal=True, recovery_state=self.state,
                config_overrides={"skills": {"include_instructions": False}},
            )
        message = str(caught.exception)
        self.assertIn("config-file overrides apply only on cold loading", message)
        self.assertIn("existing permission profile", message)
        self.assertIn("recovery --config-file replaces saved supplementary overrides", message)
        self.assertIn("not live settings", message)
        self.assertEqual(self.app.calls, [("thread/loaded/list", {})])
        self.assertEqual(recovery.read_recovery(self.state, self.app.endpoint, "thread"), before)

    async def test_consent_and_corrupt_state_fail_before_resume(self):
        with self.assertRaises(ThreadStateError):
            await configuration.resume_thread(self.app, "thread", recovery_state=self.state)
        self.assertFalse(self.app.calls)
        self.state.write_text("not a database")
        with self.assertRaises(ThreadctlError):
            await configuration.resume_thread(self.app, "thread", continue_goal=True, recovery_state=self.state)
        self.assertNotIn("thread/resume", [method for method, _ in self.app.calls])

    async def test_rejection_does_not_save_explicit_overrides(self):
        self.save({"model_context_window": 120000})
        original = self.app.request
        async def request(method, params=None):
            if method == "thread/resume":
                raise AppServerResponseError({"message": "rejected"})
            return await original(method, params)
        self.app.request = request
        with self.assertRaises(AppServerResponseError):
            await configuration.resume_thread(self.app, "thread", continue_goal=True,
                                              recovery_state=self.state,
                                              config_overrides={"model_context_window": 130000})
        self.assertEqual(recovery.read_recovery(self.state, self.app.endpoint, "thread")["config"],
                         {"model_context_window": 120000})

    async def test_concurrent_record_change_is_not_overwritten_after_resume(self):
        self.save({"model_context_window": 120000})
        original = self.app.request
        async def request(method, params=None):
            if method == "thread/resume":
                self.save({"model_context_window": 140000})
            return await original(method, params)
        self.app.request = request
        with self.assertRaises(OperationError) as caught:
            await configuration.resume_thread(self.app, "thread", continue_goal=True,
                                              recovery_state=self.state,
                                              config_overrides={"model_context_window": 130000})
        self.assertEqual(caught.exception.result["outcome"], "partial")
        self.assertEqual(recovery.read_recovery(self.state, self.app.endpoint, "thread")["config"],
                         {"model_context_window": 140000})

    async def test_resume_write_failure_preserves_loaded_identity(self):
        self.save({"model_context_window": 120000})
        with mock.patch.object(recovery, "write_recovery", side_effect=ThreadctlError("disk full")):
            with self.assertRaises(OperationError) as caught:
                await configuration.resume_thread(self.app, "thread", continue_goal=True,
                                                  recovery_state=self.state,
                                                  config_overrides={"model_context_window": 130000})
        self.assertEqual(caught.exception.result["threadId"], "thread")
        self.assertEqual(caught.exception.result["outcome"], "partial")
        self.assertEqual([method for method, _ in self.app.calls].count("thread/resume"), 1)

    async def test_inline_credentials_can_be_submitted_with_record_bypass(self):
        config = {"model_providers": {"custom": {"experimental_bearer_token": "fixture-secret"}}}
        await configuration.resume_thread(self.app, "thread", continue_goal=True, config_overrides=config)
        self.assertEqual(self.app.calls[-1][1]["config"], config)
        self.assertFalse(self.state.exists())

    async def test_cli_bypass_reaches_native_loading_without_reading_state(self):
        from test_cli import FakeContext
        argv = ["load", "thread", "--continue-goal", "--no-recovery", "--state", str(self.state)]
        with mock.patch("codex_threadctl.commands.AppServer", return_value=FakeContext(self.app)), \
             mock.patch.object(configuration, "read_recovery", side_effect=AssertionError("read")), \
             redirect_stdout(io.StringIO()):
            args = parser.build_parser().parse_args(argv)
            self.assertEqual(await args.func(args), 0)
        self.assertEqual(self.app.calls[-1], ("thread/resume", {"threadId": "thread", "excludeTurns": True}))
