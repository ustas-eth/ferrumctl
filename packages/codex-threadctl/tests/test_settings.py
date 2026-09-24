import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from codex_threadctl import appserver, cli, commands, configuration, parser, settings
from codex_threadctl.errors import (
    AppServerResponseError, DeliveryUncertain, OperationError, ThreadStateError,
    ThreadctlError,
)
from test_appserver import FakeApp
from test_cli import FakeContext


class SettingsOperations(unittest.IsolatedAsyncioTestCase):
    async def test_configure_sends_only_selected_fields_without_starting_a_turn(self):
        app = FakeApp(status="active")
        original = app.request

        async def request(method, params=None):
            if method == "thread/settings/update":
                app.calls.append((method, params))
                return {}
            return await original(method, params)

        app.request = request
        result = await configuration.configure_thread(app, "thread", model="new", effort="high")
        self.assertEqual(result["outcome"], "accepted")
        self.assertEqual(result["appliesTo"], "subsequentTurns")
        self.assertEqual(app.calls[-1], (
            "thread/settings/update", {"threadId": "thread", "model": "new", "effort": "high"},
        ))
        self.assertFalse(any(method in {"turn/start", "thread/resume"} for method, _ in app.calls))

    async def test_configure_rejects_empty_update_before_connecting(self):
        args = parser.build_parser().parse_args(["configure", "thread"])
        with mock.patch.object(commands, "AppServer") as connect:
            with self.assertRaises(ThreadStateError):
                await commands.cmd_configure(args)
        connect.assert_not_called()

    async def test_settings_timeout_is_uncertain_and_not_retried(self):
        app = FakeApp()
        original = app.request

        async def request(method, params=None):
            if method == "thread/settings/update":
                app.calls.append((method, params))
                raise OSError("connection lost")
            return await original(method, params)

        app.request = request
        with self.assertRaises(OperationError) as caught:
            await configuration.configure_thread(app, "thread", permission_profile="worker")
        self.assertEqual(caught.exception.result["outcome"], "uncertain")
        self.assertEqual(caught.exception.result["requestedSettings"], {"permissions": "worker"})
        self.assertEqual(sum(m == "thread/settings/update" for m, _ in app.calls), 1)

    async def test_unsupported_settings_update_has_no_alternative_mutation(self):
        app = FakeApp()
        original = app.request

        async def request(method, params=None):
            if method == "thread/settings/update":
                app.calls.append((method, params))
                raise AppServerResponseError({"code": -32601, "message": "unknown method"})
            return await original(method, params)

        app.request = request
        with self.assertRaises(AppServerResponseError):
            await configuration.configure_thread(app, "thread", effort="high")
        self.assertEqual([m for m, _ in app.calls], ["thread/loaded/list", "thread/settings/update"])

    async def test_resume_timeout_preserves_uncertainty_without_followup_mutation(self):
        app = FakeApp(loaded=False)
        app.request = mock.AsyncMock(side_effect=ThreadctlError("timed out"))
        with self.assertRaises(OperationError) as caught:
            await configuration.resume_thread(app, "thread", continue_goal=True)
        self.assertEqual(caught.exception.result["code"], "resumeUncertain")
        app.request.assert_awaited_once_with(
            "thread/resume", {"threadId": "thread", "excludeTurns": True},
        )

    async def test_failed_initialization_keeps_created_identity(self):
        for failure, outcome in (
            (AppServerResponseError({"message": "rejected"}), "partial"),
            (OSError("connection lost"), "uncertain"),
        ):
            with self.subTest(outcome=outcome):
                app = FakeApp()
                app.request = mock.AsyncMock(side_effect=[{"thread": {"id": "created"}}, failure])
                with self.assertRaises(OperationError) as caught:
                    await appserver.create_thread(app, "/project")
                self.assertEqual(caught.exception.result["threadId"], "created")
                self.assertEqual(caught.exception.result["outcome"], outcome)
                self.assertTrue(caught.exception.result["itemId"].startswith("amsg_"))
                self.assertEqual(app.request.await_count, 2)

    async def test_resume_applies_overrides_in_the_loading_request(self):
        app = FakeApp(loaded=False)
        original = app.request

        async def request(method, params=None):
            if method == "thread/resume":
                app.calls.append((method, params))
                return {"thread": {"id": "thread"}, "model": "new", "reasoningEffort": "high",
                        "approvalPolicy": "never", "activePermissionProfile": {"id": "worker"}}
            return await original(method, params)

        app.request = request
        result = await configuration.resume_thread(
            app, "thread", continue_goal=True, model="new", effort="high",
            permission_profile="worker", approval_policy="never",
        )
        self.assertEqual(app.calls[-1], ("thread/resume", {
            "threadId": "thread", "excludeTurns": True, "model": "new",
            "config": {"model_reasoning_effort": "high"},
            "permissions": "worker", "approvalPolicy": "never",
        }))
        self.assertEqual(result["settings"]["activePermissionProfile"], {"id": "worker"})
        self.assertFalse(any(m == "thread/settings/update" for m, _ in app.calls))

    async def test_resume_refuses_overrides_on_a_loaded_thread(self):
        app = FakeApp()
        with self.assertRaisesRegex(ThreadStateError, "configure"):
            await configuration.resume_thread(app, "thread", continue_goal=True, model="new")
        self.assertFalse(any(m == "thread/resume" for m, _ in app.calls))

    async def test_resume_race_does_not_claim_ignored_settings_were_applied(self):
        app = FakeApp(loaded=False)
        with self.assertRaises(OperationError) as caught:
            await configuration.resume_thread(app, "thread", continue_goal=True, model="new")
        self.assertEqual(caught.exception.result["outcome"], "partial")
        self.assertEqual(caught.exception.result["threadId"], "thread")
        self.assertIn("settings", caught.exception.result)

    async def test_create_effort_keeps_server_settings_separate_from_request(self):
        app = FakeApp()

        async def request(method, params=None):
            app.calls.append((method, params))
            if method == "thread/start":
                return {"thread": {"id": "created"}, "model": "resolved",
                        "reasoningEffort": "high", "approvalPolicy": "never",
                        "activePermissionProfile": {"id": "worker"}}
            return {}

        app.request = request
        result = await appserver.create_thread(app, "/project", effort="high")
        self.assertEqual(app.calls[0][1], {"cwd": "/project", "config": {"model_reasoning_effort": "high"}})
        self.assertIsNone(result["permissionRequest"]["permissionProfile"])
        self.assertEqual(result["settings"]["activePermissionProfile"], {"id": "worker"})

    async def test_inspect_retains_metadata_and_goal_when_history_fails(self):
        args = parser.build_parser().parse_args(["inspect", "thread", "--json"])
        app = SimpleNamespace(endpoint="unix://")
        with (
            mock.patch.object(commands, "AppServer", return_value=FakeContext(app)),
            mock.patch.object(commands, "read_thread", mock.AsyncMock(return_value={
                "id": "thread", "model": "selected", "reasoningEffort": "high", "path": None,
            })),
            mock.patch.object(commands, "list_loaded", mock.AsyncMock(return_value=["thread"])),
            mock.patch.object(commands, "get_goal", mock.AsyncMock(return_value={"status": "active"})),
            mock.patch.object(commands, "list_turn_page", mock.AsyncMock(side_effect=ThreadctlError("history timeout"))),
            redirect_stdout(io.StringIO()) as output,
        ):
            code = await commands.cmd_inspect(args)
        result = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(result["thread"]["model"], "selected")
        self.assertEqual(result["goal"]["status"], "active")
        self.assertEqual(result["historyError"], "history timeout")
        self.assertIsNone(result["latestTurn"])
        self.assertIn("no local rollout", result["recordedSettingsError"])


class SettingsObservations(unittest.TestCase):
    def test_latest_turn_record_is_attributed_and_does_not_read_message_claims(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rollout.jsonl"
            path.write_text("\n".join(json.dumps(row) for row in [
                {"type": "turn_context", "timestamp": "2026-01-01T00:00:00Z",
                 "payload": {"turn_id": "old", "model": "old-model"}},
                {"type": "turn_context", "timestamp": "2026-01-01T00:01:00Z",
                 "payload": {"turn_id": "new", "model": "new-model", "effort": "high",
                             "active_permission_profile": {"id": "worker"},
                             "permission_profile": {"network": "enabled"}}},
                {"type": "response_item", "payload": {"type": "turn_context", "model": "fake"}},
            ]))
            result, error = settings.read_recorded_settings(str(path))
        self.assertIsNone(error)
        self.assertEqual(result["turnId"], "new")
        self.assertEqual(result["source"], "local-rollout")
        self.assertEqual(result["observedAt"], 1767225660)
        self.assertEqual(result["permissionProfile"]["network"], "enabled")

    def test_missing_rollout_does_not_invent_current_settings(self):
        result, error = settings.read_recorded_settings(None)
        self.assertIsNone(result)
        self.assertIsNotNone(error)

    def test_malformed_returned_profile_is_not_confirmation(self):
        self.assertEqual(settings.unconfirmed_settings(
            {"permissions": "worker"}, {"activePermissionProfile": "worker"},
        ), ["permissions"])

    def test_json_failure_keeps_uncertainty_identifiers(self):
        with (
            mock.patch.object(cli, "dispatch", mock.AsyncMock(side_effect=DeliveryUncertain("turn", "client"))),
            redirect_stdout(io.StringIO()) as output,
            redirect_stderr(io.StringIO()),
        ):
            code = cli.main(["start", "thread", "input", "--json"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue())["error"], {
            "code": "deliveryUncertain", "outcome": "uncertain", "turnId": "turn",
            "clientMessageId": "client", "message": "input outcome is uncertain for turn turn; client message id client",
        })

    def test_rejection_remains_distinct_from_uncertainty(self):
        with (
            mock.patch.object(cli, "dispatch", mock.AsyncMock(side_effect=AppServerResponseError({"code": -32601, "message": "unknown method"}))),
            redirect_stdout(io.StringIO()) as output,
            redirect_stderr(io.StringIO()),
        ):
            code = cli.main(["configure", "thread", "--effort", "high", "--json"])
        self.assertEqual(code, 1)
        error = json.loads(output.getvalue())["error"]
        self.assertEqual(error["outcome"], "rejected")
        self.assertEqual(error["rpcCode"], -32601)
