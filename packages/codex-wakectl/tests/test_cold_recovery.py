"""Persisted configuration and delivery transitions through the real clients."""
import argparse
import asyncio
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from codex_threadctl.errors import ThreadStateError, ThreadctlError
from codex_wakectl import commands, delivery, parser, state
from codex_wakectl.actions import build_action
from codex_wakectl.conditions import new_job
from codex_wakectl.errors import EventDeliveryUncertain, WakectlError


class RecoveryApp:
    timeout = 0.01

    def __init__(self, *, loaded=False, goal=None, continuation=None):
        self.loaded = loaded
        self.goal = goal
        self.continuation = continuation
        self.status = "idle"
        self.turn_id = "old-turn"
        self.calls = []
        self.turn_notifications = []

    async def request(self, method, params=None):
        self.calls.append((method, params))
        if method == "thread/loaded/list":
            return {"data": ["target"] if self.loaded else []}
        if method == "thread/goal/get":
            return {"goal": self.goal}
        if method == "thread/turns/list":
            return {"data": [{"id": self.turn_id, "status":
                              "inProgress" if self.status == "active" else "completed"}]}
        if method == "thread/resume":
            self.loaded = True
            if self.continuation in {"active", "finished"}:
                self.turn_id = "goal-turn"
                self.status = "active" if self.continuation == "active" else "idle"
            return {"thread": {"id": "target"}, "activePermissionProfile": {"id": "worker"}}
        if method == "thread/read":
            return {"thread": {"id": "target", "status": {"type": self.status}}}
        if method == "thread/inject_items":
            if self.continuation == "delayed":
                self.turn_id, self.status = "goal-turn", "active"
            return {}
        if method == "turn/start":
            self.turn_id, self.status = "wake-turn", "active"
            return {"turn": {"id": self.turn_id, "status": "inProgress"}}
        raise AssertionError(method)


def job_with_config(config=None):
    return new_job({"type": "time", "at": 1}, "target", {
        "type": "event", "resume": True,
        **({"resumeConfig": config} if config is not None else {}),
    }, "unix://")


class ScheduledConfigTests(unittest.TestCase):
    def test_config_file_requires_event_resume_before_reading_file(self):
        for options in (
            [], ["--input", "continue"], ["--resume", "--input", "continue"],
            ["--resume", "legacy message"],
        ):
            with self.subTest(options=options):
                args = parser.build_parser().parse_args([
                    "add", "time", "--after", "1m", "--to", "target",
                    "--config-file", "/missing", *options,
                ])
                with self.assertRaises(WakectlError):
                    build_action(args)

    def test_invalid_config_does_not_create_a_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config, queue = root / "worker.toml", root / "jobs.sqlite3"
            for contents in ('invalid = [', 'value = 2026-01-01', '[profiles.worker]\nmodel="x"'):
                config.write_text(contents)
                args = parser.build_parser().parse_args([
                    "add", "time", "--after", "1m", "--to", "target", "--resume",
                    "--config-file", str(config), "--state", str(queue),
                ])
                with self.assertRaises(ThreadctlError):
                    asyncio.run(commands.cmd_add(args))
                self.assertFalse(queue.exists())

    def test_snapshot_survives_file_change_and_json_hides_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config, queue = root / "worker.toml", root / "jobs.sqlite3"
            config.write_text('model_reasoning_effort = "low"\nprivate_value = "fixture-secret"\n')
            args = parser.build_parser().parse_args([
                "add", "time", "--after", "1m", "--to", "target", "--resume",
                "--config-file", str(config), "--state", str(queue), "--json",
            ])
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(asyncio.run(commands.cmd_add(args)), 0)
            config.write_text('model_reasoning_effort = "high"')
            config.unlink()
            saved = state.list_jobs(queue)[0]
            self.assertEqual(saved["action"]["resumeConfig"], {
                "model_reasoning_effort": "low", "private_value": "fixture-secret",
            })
            public = json.loads(output.getvalue())["job"]
            self.assertEqual(public["action"]["configRequest"]["keys"],
                             ["model_reasoning_effort", "private_value"])
            self.assertNotIn("fixture-secret", output.getvalue())
            with contextlib.redirect_stdout(io.StringIO()) as output:
                commands.cmd_list(argparse.Namespace(state=queue, all=True, json=True))
            self.assertNotIn("fixture-secret", output.getvalue())
            self.assertEqual(state.list_jobs(queue)[0]["action"], saved["action"])

    def test_all_conditions_accept_the_same_cold_config(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "worker.toml"
            config.write_text('default_permissions = "worker"')
            for condition in (
                ["time", "--after", "1m"], ["goal", "worker", "--status", "complete"],
                ["stop", "worker"], ["cmd"],
            ):
                with self.subTest(condition=condition):
                    suffix = ["--", "true"] if condition == ["cmd"] else []
                    args = parser.build_parser().parse_args([
                        "add", *condition, "--to", "target", "--resume",
                        "--config-file", str(config), *suffix,
                    ])
                    self.assertEqual(build_action(args)["resumeConfig"],
                                     {"default_permissions": "worker"})


class ColdDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_cold_delivery_applies_snapshot_and_starts_one_empty_turn(self):
        app = RecoveryApp()
        config = {"default_permissions": "worker", "model_reasoning_effort": "low"}
        result = await delivery.deliver_event(app, job_with_config(config), "ready")
        self.assertEqual(result["delivery"], "resumedStarted")
        self.assertTrue(result["loading"]["configSubmitted"])
        self.assertEqual([params["config"] for method, params in app.calls
                          if method == "thread/resume"], [config])
        self.assertEqual([params["input"] for method, params in app.calls
                          if method == "turn/start"], [[]])

    async def test_loaded_delivery_does_not_reapply_snapshot(self):
        app = RecoveryApp(loaded=True)
        result = await delivery.deliver_event(app, job_with_config({"model": "other"}), "ready")
        self.assertEqual(result["loading"], {"outcome": "alreadyLoaded", "configSubmitted": False})
        self.assertFalse(any(method in {"thread/resume", "thread/settings/update"}
                             for method, _ in app.calls))

    async def test_resume_does_not_enable_notifications_for_loaded_active_work(self):
        app = RecoveryApp(loaded=True)
        app.status = "active"
        with self.assertRaises(ThreadStateError):
            await delivery.deliver_event(app, job_with_config({"model": "other"}), "ready")
        self.assertFalse(any(method in {"thread/resume", "thread/inject_items", "turn/start"}
                             for method, _ in app.calls))

    async def test_active_goal_continuations_do_not_get_a_second_start(self):
        for continuation, expected in (("active", "resumedActive"), ("delayed", "resumedContinued")):
            with self.subTest(continuation=continuation):
                app = RecoveryApp(goal={"status": "active"}, continuation=continuation)
                result = await delivery.deliver_event(app, job_with_config(), "ready")
                self.assertEqual(result["delivery"], expected)
                self.assertEqual(result["turnId"], "goal-turn")
                self.assertFalse(any(method == "turn/start" for method, _ in app.calls))

    async def test_resumed_goal_ending_before_injection_gets_event_attention(self):
        app = RecoveryApp(goal={"status": "active"}, continuation="active")
        original = app.request

        async def finish_before_injection(method, params=None):
            if method == "thread/inject_items":
                app.status = "idle"
                app.goal = {"status": "complete"}
            return await original(method, params)

        app.request = finish_before_injection
        result = await delivery.deliver_event(app, job_with_config(), "ready")
        self.assertEqual(result["delivery"], "resumedStarted")
        self.assertEqual(result["turnId"], "wake-turn")
        self.assertEqual(sum(method == "turn/start" for method, _ in app.calls), 1)

    async def test_already_finished_continuation_does_not_swallow_event_wake(self):
        app = RecoveryApp(goal={"status": "active"}, continuation="finished")
        result = await delivery.deliver_event(app, job_with_config(), "ready")
        self.assertEqual(result["turnId"], "wake-turn")
        self.assertEqual(sum(method == "turn/start" for method, _ in app.calls), 1)

    async def test_unconfirmed_continuation_records_event_and_loading(self):
        app = RecoveryApp(goal={"status": "active"})
        with self.assertRaises(EventDeliveryUncertain) as raised:
            await delivery.deliver_event(app, job_with_config(), "ready")
        self.assertEqual(raised.exception.loading["outcome"], "resumed")
        self.assertFalse(any(method == "turn/start" for method, _ in app.calls))

    async def test_uncertain_injection_preserves_loading_without_starting_a_turn(self):
        app = RecoveryApp()
        original = app.request

        async def failing_request(method, params=None):
            if method == "thread/inject_items":
                raise OSError("lost injection response")
            return await original(method, params)

        app.request = failing_request
        job = job_with_config({"model_reasoning_effort": "low"})
        with self.assertRaises(EventDeliveryUncertain) as raised:
            await delivery.deliver_event(app, job, "ready")
        self.assertEqual(raised.exception.item_id, delivery.event_item_id(job))
        self.assertTrue(raised.exception.loading["configSubmitted"])
        self.assertFalse(any(method == "turn/start" for method, _ in app.calls))

    async def test_failure_after_injection_is_not_retried_by_runner(self):
        app = RecoveryApp()
        original = app.request

        async def failing_request(method, params=None):
            if method == "thread/goal/get" and any(m == "thread/inject_items" for m, _ in app.calls):
                raise OSError("connection lost after injection")
            return await original(method, params)

        app.request = failing_request

        @contextlib.asynccontextmanager
        async def attached(*args):
            yield app

        with tempfile.TemporaryDirectory() as directory:
            queue = Path(directory) / "jobs.sqlite3"
            job = job_with_config({"model_reasoning_effort": "low"})
            state.insert_job(queue, job)
            args = parser.build_parser().parse_args(["run", "--state", str(queue), "--json"])
            with mock.patch.object(commands, "wakectl_appserver", attached), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(await commands.cmd_run(args), 1)
                self.assertEqual(await commands.cmd_run(args), 0)
            saved = state.list_jobs(queue, include_all=True)[0]
            self.assertEqual(saved["status"], "uncertain")
            self.assertEqual(saved["lastEventItemId"], delivery.event_item_id(job))
            self.assertTrue(saved["lastLoading"]["configSubmitted"])
            self.assertEqual(sum(m == "thread/inject_items" for m, _ in app.calls), 1)
