import io
import json
import unittest
from contextlib import redirect_stdout
from unittest import mock

from codex_threadctl import attention, communication_commands, parser
from codex_threadctl.errors import (
    AppServerResponseError, DirectInputUnsupported, NotificationUncertain,
    OperationError, ThreadctlError, ThreadNotLoaded,
)
from test_appserver import FakeApp
from test_cli import FakeContext


class CommunicationApp(FakeApp):
    """Exercise real client functions; only JSON-RPC is simulated."""
    def __init__(self, *, goal=None, continue_on_resume=False, **kwargs):
        super().__init__(**kwargs)
        self.goal = goal
        self.continue_on_resume = continue_on_resume
        self.resumed = False

    async def request(self, method, params=None):
        if method == "thread/goal/get":
            self.calls.append((method, params))
            return {"goal": self.goal}
        if method == "thread/inject_items":
            self.calls.append((method, params))
            return {}
        if method == "thread/resume":
            self.loaded = True
            self.resumed = True
            if self.continue_on_resume:
                self.actual_turn_id = "goal-continuation"
                self.status = "active"
        if method == "turn/start":
            self.actual_turn_id = "submission"
        return await super().request(method, params)


class AttentionTests(unittest.IsolatedAsyncioTestCase):
    async def test_plain_send_is_agent_context_with_no_turn_request(self):
        for status in ("active", "idle", "systemError"):
            with self.subTest(status=status):
                app = CommunicationApp(status=status)
                result = await attention.send_message(app, "thread", "peer", "Full report")
                self.assertEqual(result["messageRole"], "agent")
                self.assertEqual(result["outcome"], "accepted")
                self.assertEqual([m for m, _ in app.calls],
                                 ["thread/loaded/list", "thread/inject_items"])
                item = app.calls[-1][1]["items"][0]
                self.assertEqual(item["type"], "agent_message")
                self.assertEqual(item["author"], "peer")
                self.assertEqual(item["content"][0]["text"], "Full report")
                self.assertEqual(item["id"], result["itemId"])

    async def test_send_wake_uses_empty_input_only_when_stopped(self):
        for status in ("idle", "systemError", "active"):
            with self.subTest(status=status):
                app = CommunicationApp(status=status)
                result = await attention.send_message(app, "thread", "peer", "Report", wake=True)
                self.assertEqual(result["outcome"], "accepted")
                starts = [p for m, p in app.calls if m == "turn/start"]
                self.assertEqual(starts, [] if status == "active" else
                                 [{"threadId": "thread", "input": []}])
                self.assertEqual(result["wake"]["outcome"],
                                 "notSubmittedActive" if status == "active" else "confirmedStarted")

    async def test_send_never_silently_loads(self):
        app = CommunicationApp(loaded=False)
        with self.assertRaises(ThreadNotLoaded):
            await attention.send_message(app, "thread", "peer", "Report", wake=True)
        self.assertFalse(app.resumed)

    async def test_cold_wake_submits_config_and_one_empty_turn(self):
        app = CommunicationApp(loaded=False)
        config = {"skills": {"bundled": {"enabled": False}}}
        result = await attention.wake_with_resume(app, "thread", config)
        self.assertTrue(result["loading"]["configSubmitted"])
        self.assertEqual(result["outcome"], "confirmedStarted")
        resume = [p for m, p in app.calls if m == "thread/resume"]
        self.assertEqual(resume[0]["config"], config)
        self.assertEqual(len([m for m, _ in app.calls if m == "turn/start"]), 1)

    async def test_live_wake_does_not_apply_cold_configuration(self):
        for status in ("idle", "active", "systemError"):
            app = CommunicationApp(status=status)
            result = await attention.wake_with_resume(app, "thread", {"model": "other"})
            self.assertEqual(result["loading"], {"outcome": "alreadyLoaded", "configSubmitted": False})
            self.assertFalse(app.resumed)
            self.assertNotIn("thread/settings/update", [m for m, _ in app.calls])

    async def test_resume_goal_continuation_does_not_get_a_second_turn(self):
        app = CommunicationApp(loaded=False, goal={"status": "active"}, continue_on_resume=True)
        result = await attention.send_message(app, "thread", "peer", "Report", wake=True, resume=True)
        self.assertEqual(result["wake"]["outcome"], "notSubmittedActive")
        self.assertEqual(result["wake"]["turnId"], "goal-continuation")
        self.assertNotIn("turn/start", [m for m, _ in app.calls])

    async def test_finished_continuation_before_send_does_not_swallow_wake(self):
        app = CommunicationApp(loaded=False, goal={"status": "active"}, continue_on_resume=True)
        original = app.request
        async def request(method, params=None):
            result = await original(method, params)
            if method == "thread/resume":
                app.status = "idle"
                app.turn_status = "completed"
                app.goal = {"status": "complete"}
            return result
        app.request = request
        result = await attention.send_message(app, "thread", "peer", "New question", wake=True, resume=True)
        self.assertEqual(result["wake"]["outcome"], "confirmedStarted")
        methods = [m for m, _ in app.calls]
        self.assertEqual(methods.count("turn/start"), 1)
        self.assertLess(methods.index("thread/inject_items"), methods.index("turn/start"))

    async def test_delayed_goal_continuation_is_observed_not_started(self):
        app = CommunicationApp(loaded=False, goal={"status": "active"})
        async def continue_goal(_):
            app.actual_turn_id = "delayed-goal-turn"
        with mock.patch.object(attention.asyncio, "sleep", side_effect=continue_goal):
            result = await attention.wake_with_resume(app, "thread")
        self.assertEqual(result["turnId"], "delayed-goal-turn")
        self.assertNotIn("turn/start", [m for m, _ in app.calls])

    async def test_unobserved_goal_continuation_is_not_claimed_as_success(self):
        app = CommunicationApp(loaded=False, goal={"status": "active"})
        app.timeout = 0
        result = await attention.wake_with_resume(app, "thread")
        self.assertEqual(result["outcome"], "continuationUnconfirmed")
        self.assertNotIn("turn/start", [m for m, _ in app.calls])

    async def test_disabled_goals_do_not_block_cold_wake(self):
        app = CommunicationApp(loaded=False)
        with mock.patch.object(attention, "get_goal", side_effect=AppServerResponseError(
            {"message": "goals feature is disabled"},
        )):
            result = await attention.wake_with_resume(app, "thread")
        self.assertEqual(result["outcome"], "confirmedStarted")

    async def test_unreadable_goal_is_not_assumed_absent(self):
        app = CommunicationApp(loaded=False)
        with mock.patch.object(attention, "get_goal", side_effect=ThreadctlError("timeout")):
            with self.assertRaises(ThreadctlError):
                await attention.wake_with_resume(app, "thread")
        self.assertFalse(app.resumed)

    async def test_goal_activated_during_loading_uses_continuation_path(self):
        app = CommunicationApp(loaded=False, continue_on_resume=True)
        with mock.patch.object(attention, "get_goal", side_effect=[None, {"status": "active"}]):
            result = await attention.wake_with_resume(app, "thread")
        self.assertEqual(result["outcome"], "confirmedResumed")
        self.assertNotIn("turn/start", [m for m, _ in app.calls])

    async def test_accepted_message_survives_failed_wake_in_result(self):
        for failure in (OSError("connection lost"), ThreadctlError("bad response")):
            app = CommunicationApp()
            with mock.patch.object(attention, "wake_thread", side_effect=failure):
                result = await attention.send_message(app, "thread", "peer", "Report", wake=True)
            self.assertEqual(result["outcome"], "partial")
            self.assertEqual(result["messageOutcome"], "accepted")
            self.assertTrue(result["itemId"].startswith("amsg_"))
            self.assertIn("wake", result)

    async def test_rejected_or_uncertain_wake_is_a_partial_send(self):
        for outcome in ("rejected", "uncertain", "notLoaded"):
            app = CommunicationApp()
            with mock.patch.object(attention, "wake_thread", return_value={"outcome": outcome}):
                result = await attention.send_message(app, "thread", "peer", "Report", wake=True)
            self.assertEqual(result["outcome"], "partial")
            self.assertEqual(result["wake"]["outcome"], outcome)
            self.assertEqual(len([m for m, _ in app.calls if m == "thread/inject_items"]), 1)

    async def test_uncertain_send_never_wakes_or_retries(self):
        app = CommunicationApp()
        with mock.patch.object(attention, "notify_thread", side_effect=NotificationUncertain("amsg_test")):
            with self.assertRaises(NotificationUncertain) as raised:
                await attention.send_message(app, "thread", "peer", "Report", wake=True)
        self.assertEqual(raised.exception.item_id, "amsg_test")
        self.assertEqual(app.calls, [])

    async def test_cold_send_error_preserves_loading_and_message_identifier(self):
        app = CommunicationApp(loaded=False)
        with mock.patch.object(attention, "notify_thread", side_effect=NotificationUncertain("amsg_test")):
            with self.assertRaises(OperationError) as raised:
                await attention.send_message(app, "thread", "peer", "Report", wake=True, resume=True)
        self.assertEqual(raised.exception.result["loading"]["outcome"], "resumed")
        self.assertEqual(raised.exception.result["messageDelivery"]["itemId"], "amsg_test")
        self.assertNotIn("turn/start", [m for m, _ in app.calls])

    async def test_parent_owned_rejection_does_not_try_alternative_controls(self):
        app = CommunicationApp()
        original = app.request
        async def request(method, params=None):
            if method == "thread/inject_items":
                raise AppServerResponseError({"message": "direct app-server input is not allowed for multi-agent v2 sub-agents"})
            return await original(method, params)
        app.request = request
        with self.assertRaises(DirectInputUnsupported):
            await attention.send_message(app, "thread", "peer", "Report", wake=True)
        self.assertNotIn("turn/start", [m for m, _ in app.calls])


class CommunicationCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_input_selects_start_or_exact_steer_and_reports_user_role(self):
        for flags in ([], ["--turn", "submission"]):
            app = CommunicationApp()
            args = parser.build_parser().parse_args(["input", "thread", "Text", "--json", *flags])
            with mock.patch.object(communication_commands, "AppServer", return_value=FakeContext(app)), redirect_stdout(io.StringIO()) as output:
                self.assertEqual(await args.func(args), 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result["messageRole"], "user")
            method = "turn/steer" if flags else "turn/start"
            params = next(p for m, p in app.calls if m == method)
            self.assertEqual(params["input"][0]["text"], "Text")
            if flags:
                self.assertEqual(params["expectedTurnId"], "submission")

    async def test_send_cli_partial_has_nonzero_exit_and_reconciliation_id(self):
        app = CommunicationApp()
        args = parser.build_parser().parse_args(["send", "thread", "Report", "--from", "peer", "--wake", "--json"])
        with mock.patch.object(communication_commands, "AppServer", return_value=FakeContext(app)), mock.patch.object(attention, "wake_thread", return_value={"outcome": "uncertain"}), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(await args.func(args), 1)
        self.assertEqual(json.loads(output.getvalue())["messageOutcome"], "accepted")
        self.assertIn("itemId", json.loads(output.getvalue()))

    async def test_invalid_combinations_fail_before_connecting(self):
        for flags in (["--resume"], ["--config-file", "/missing"]):
            args = parser.build_parser().parse_args(["send", "thread", "Report", *flags])
            with mock.patch.object(communication_commands, "AppServer") as server:
                with self.assertRaises(ThreadctlError):
                    await args.func(args)
                server.assert_not_called()

    def test_load_and_resume_share_implementation(self):
        canonical = parser.build_parser().parse_args(["load", "thread", "--continue-goal"])
        legacy = parser.build_parser().parse_args(["resume", "thread", "--continue-goal"])
        self.assertIs(canonical.func, legacy.func)
