from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from codex_threadctl.errors import ThreadctlError
from codex_wakectl import commands
from codex_wakectl import conditions
from codex_wakectl import parser
from codex_wakectl import parsing
from codex_wakectl import state
from codex_wakectl import systemd
from codex_wakectl.actions import build_action, input_action
from codex_wakectl.errors import WakectlError


class ParseTests(unittest.TestCase):
    def test_version(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaisesRegex(SystemExit, "0"):
                parser.build_parser().parse_args(["--version"])
        self.assertEqual(output.getvalue(), "codex-wakectl 0.5.0\n")

    def test_parse_duration(self) -> None:
        self.assertEqual(parsing.parse_duration("10s"), 10)
        self.assertEqual(parsing.parse_duration("5m"), 300)
        self.assertEqual(parsing.parse_duration("2h"), 7200)
        self.assertEqual(parsing.parse_duration("1d"), 86400)
        self.assertEqual(parsing.parse_duration("1_000s"), 1000)
        self.assertEqual(parsing.parse_duration("3m30s"), 210)
        self.assertEqual(parsing.parse_duration("1d2h3m4s"), 93784)

    def test_parse_duration_rejects_missing_unit(self) -> None:
        with self.assertRaises(argparse.ArgumentTypeError):
            parsing.parse_duration("300")

    def test_parse_duration_rejects_partial_or_zero_values(self) -> None:
        for value in (
            "3m 30s",
            "3m30",
            "3x30s",
            "0s",
            "",
            "1m2m",
            "1s1m",
            "1_m",
            "1__0s",
        ):
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    parsing.parse_duration(value)

    def test_add_accepts_compound_duration(self) -> None:
        args = parser.build_parser().parse_args(
            [
                "add",
                "time",
                "--after",
                "3m30s",
                "--to",
                "thread",
                "message",
            ]
        )
        self.assertEqual(args.after, 210)

    def test_parse_tokens_are_plain_integers(self) -> None:
        self.assertEqual(parsing.parse_positive_int("3000000"), 3000000)
        self.assertEqual(parsing.parse_positive_int("3_000_000"), 3000000)

    def test_parse_positive_float(self) -> None:
        self.assertEqual(parsing.parse_positive_float("1.5"), 1.5)
        for value in ("0", "nan", "inf", "-inf"):
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    parsing.parse_positive_float(value)

    def test_removed_immediate_command_has_migration_hint(self) -> None:
        args = parser.build_parser().parse_args(["send", "thread", "message"])
        with self.assertRaisesRegex(WakectlError, "codex-threadctl start"):
            args.func(args)

    def test_removed_commands_are_hidden_from_help(self) -> None:
        output = parser.build_parser().format_help()
        self.assertNotIn("==SUPPRESS==", output)
        self.assertNotIn("    send", output)
        self.assertIn("{add,wait,run,list,cancel,systemd}", output)

    def test_wait_help_distinguishes_synchronous_polling_from_jobs(self) -> None:
        root = parser.build_parser()
        commands = next(
            action
            for action in root._actions
            if isinstance(action, argparse._SubParsersAction)
        )
        wait = commands.choices["wait"]
        output = " ".join(wait.format_help().split())
        self.assertIn("Poll a condition in this process", output)
        self.assertIn("does not persist a wake job", output)
        self.assertNotIn("--state", output)

        conditions = next(
            action
            for action in wait._actions
            if isinstance(action, argparse._SubParsersAction)
        )
        command_output = " ".join(conditions.choices["cmd"].format_help().split())
        self.assertIn("does not monitor an existing process", command_output)
        self.assertIn("create a wake job", command_output)

    def test_parse_statuses(self) -> None:
        self.assertEqual(
            parsing.parse_statuses("complete,budgetLimited"),
            ["complete", "budgetLimited"],
        )
        with self.assertRaises(argparse.ArgumentTypeError):
            parsing.parse_statuses("done")

    def test_wait_options_after_condition(self) -> None:
        args = parser.build_parser().parse_args(
            ["wait", "time", "--after", "1s", "--max-wait", "2s"]
        )
        self.assertEqual(args.after, 1)
        self.assertEqual(args.max_wait, 2)

    def test_wait_poll_interval_must_be_positive(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parser.build_parser().parse_args(
                    ["wait", "time", "--after", "1s", "--poll-interval", "0"]
                )

    def test_add_globals_after_condition(self) -> None:
        args = parser.build_parser().parse_args(
            [
                "add",
                "time",
                "--after",
                "1s",
                "--to",
                "thread",
                "message",
                "--state",
                "/tmp/jobs.sqlite3",
            ]
        )
        self.assertEqual(str(args.state), "/tmp/jobs.sqlite3")

    def test_add_stores_wake_policy_options(self) -> None:
        args = parser.build_parser().parse_args(
            [
                "add",
                "time",
                "--after",
                "1s",
                "--to",
                "thread",
                "--allow-active",
                "message",
                "--timeout",
                "45",
            ]
        )
        self.assertTrue(args.allow_active)
        self.assertEqual(args.timeout, 45)

    def test_add_defaults_to_an_event_wake(self) -> None:
        args = parser.build_parser().parse_args(
            ["add", "time", "--after", "1m", "--to", "thread"]
        )
        self.assertEqual(build_action(args), {"type": "event"})

    def test_add_exposes_event_and_input_policies_explicitly(self) -> None:
        notify = parser.build_parser().parse_args(
            [
                "add",
                "goal",
                "worker",
                "--status",
                "complete",
                "--to",
                "main",
                "--notify-active",
                "--resume",
            ]
        )
        send = parser.build_parser().parse_args(
            [
                "add",
                "time",
                "--after",
                "1m",
                "--to",
                "thread",
                "--input",
                "continue",
            ]
        )
        self.assertEqual(
            build_action(notify),
            {"type": "event", "notifyActive": True, "resume": True},
        )
        self.assertEqual(
            build_action(send),
            {"type": "input", "message": "continue"},
        )

    def test_add_rejects_unsafe_action_combinations(self) -> None:
        cases = [
            ["--input", "continue", "--notify-active"],
            ["--input", "continue", "--resume"],
            ["--input", "continue", "--allow-active"],
        ]
        for options in cases:
            with self.subTest(options=options):
                args = parser.build_parser().parse_args(
                    ["add", "time", "--after", "1m", "--to", "thread", *options]
                )
                with self.assertRaises(WakectlError):
                    build_action(args)

    def test_legacy_positional_message_keeps_input_semantics(self) -> None:
        args = parser.build_parser().parse_args(
            [
                "add",
                "time",
                "--after",
                "1m",
                "--to",
                "thread",
                "old message",
            ]
        )
        self.assertEqual(
            build_action(args),
            {"type": "input", "message": "old message", "legacy": True},
        )

    def test_add_stop_repeat_options(self) -> None:
        args = parser.build_parser().parse_args(
            [
                "add",
                "stop",
                "worker",
                "--repeat",
                "--max-fires",
                "3",
                "--to",
                "orchestrator",
                "worker stopped",
            ]
        )
        condition = conditions.build_stop_condition(args)
        self.assertEqual(condition["type"], "stop")
        self.assertTrue(condition["repeat"])
        self.assertEqual(condition["maxFires"], 3)

    def test_agent_tree_scope_is_available_for_path_conditions_and_targets(self) -> None:
        add_args = parser.build_parser().parse_args(
            [
                "add",
                "goal",
                "/root/worker",
                "--status",
                "complete",
                "--to",
                "/root",
                "worker complete",
                "--tree",
                "root-thread",
            ]
        )
        wait_args = parser.build_parser().parse_args(
            [
                "wait",
                "stop",
                "/root/worker",
                "--tree",
                "root-thread",
            ]
        )

        self.assertEqual(add_args.tree, "root-thread")
        self.assertEqual(wait_args.tree, "root-thread")

    def test_add_cmd_requires_wakectl_options_before_message(self) -> None:
        valid = parser.build_parser().parse_args(
            [
                "add",
                "cmd",
                "--tree",
                "root-thread",
                "--to",
                "thread",
                "ready",
                "--",
                "test",
                "-f",
                "done",
            ]
        )
        misplaced = parser.build_parser().parse_args(
            [
                "add",
                "cmd",
                "--to",
                "thread",
                "ready",
                "--tree",
                "root-thread",
                "--",
                "test",
                "-f",
                "done",
            ]
        )

        self.assertEqual(valid.tree, "root-thread")
        self.assertEqual(build_action(valid)["message"], "ready")
        self.assertEqual(valid.argv, ["test", "-f", "done"])
        with self.assertRaisesRegex(
            WakectlError,
            "--tree must appear before MESSAGE",
        ):
            build_action(misplaced)

    def test_stop_accepts_exact_or_latest_turn(self) -> None:
        add_args = parser.build_parser().parse_args(
            [
                "add",
                "stop",
                "worker",
                "--turn",
                "latest",
                "--to",
                "orchestrator",
                "worker stopped",
            ]
        )
        wait_args = parser.build_parser().parse_args(
            ["wait", "stop", "worker", "--turn", "turn-1"]
        )

        self.assertEqual(conditions.build_stop_condition(add_args)["turnId"], "latest")
        self.assertEqual(conditions.build_stop_condition(wait_args)["turnId"], "turn-1")

    def test_run_replaces_tick(self) -> None:
        args = parser.build_parser().parse_args(["run", "--limit", "1"])
        self.assertEqual(args.limit, 1)
        self.assertIs(args.func, commands.cmd_run)

        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parser.build_parser().parse_args(["tick"])
            with self.assertRaises(SystemExit):
                parser.build_parser().parse_args(["run", "--allow-active"])

    def test_systemd_install_options(self) -> None:
        args = parser.build_parser().parse_args(["systemd", "install", "--interval", "5m"])
        self.assertEqual(args.interval, 300)
        self.assertIs(args.func, commands.cmd_systemd_install)

class ConditionTests(unittest.TestCase):
    def test_goal_condition_requires_predicate(self) -> None:
        args = argparse.Namespace(
            thread_id="thread",
            status=None,
            tokens_left_lte=None,
            tokens_used_gte=None,
            tokens_used_every=None,
            time_used_gte=None,
            time_used_every=None,
        )
        with self.assertRaises(WakectlError):
            conditions.build_goal_condition(args)

    def test_goal_condition_rejects_multiple_repeating_predicates(self) -> None:
        args = argparse.Namespace(
            thread_id="thread",
            status=None,
            tokens_left_lte=None,
            tokens_used_gte=None,
            tokens_used_every=3000000,
            time_used_gte=None,
            time_used_every=1800,
        )
        with self.assertRaises(WakectlError):
            conditions.build_goal_condition(args)

    def test_goal_max_fires_requires_repeating_predicate(self) -> None:
        args = argparse.Namespace(
            thread_id="thread",
            status="complete",
            tokens_left_lte=None,
            tokens_used_gte=None,
            tokens_used_every=None,
            time_used_gte=None,
            time_used_every=None,
            max_fires=2,
        )
        with self.assertRaises(WakectlError):
            conditions.build_goal_condition(args)

    def test_goal_repeating_bucket(self) -> None:
        condition = {"type": "goal", "threadId": "t", "tokensUsedEvery": 3000000}
        job = {"lastTokensUsedBucket": 1}
        goal = {"tokensUsed": 6200000, "status": "active"}

        class App:
            async def request(self, method, params):
                return {"goal": goal}

        ready, updates, _ = asyncio.run(conditions.goal_condition_ready(App(), condition, job))
        self.assertTrue(ready)
        self.assertEqual(updates["lastTokensUsedBucket"], 2)

    def test_goal_match_reason_describes_the_observed_values(self) -> None:
        condition = {
            "type": "goal",
            "threadId": "t",
            "statuses": ["complete"],
            "tokensUsedGte": 1000,
        }
        goal = {"tokensUsed": 1200, "status": "complete"}

        class App:
            async def request(self, method, params):
                return {"goal": goal}

        ready, _, reason = asyncio.run(
            conditions.goal_condition_ready(App(), condition)
        )
        self.assertTrue(ready)
        self.assertEqual(reason, "status is complete; tokens used 1200")

    def test_goal_repeating_bucket_rebases_after_counter_reset(self) -> None:
        condition = {"type": "goal", "threadId": "t", "tokensUsedEvery": 1000}
        job = {"lastTokensUsedBucket": 4}
        goal = {"tokensUsed": 250, "status": "active"}

        class App:
            async def request(self, method, params):
                return {"goal": goal}

        ready, updates, reason = asyncio.run(
            conditions.goal_condition_ready(App(), condition, job)
        )

        self.assertFalse(ready)
        self.assertEqual(updates["lastTokensUsedBucket"], 0)
        self.assertEqual(reason, "goal usage counters reset")

    def test_goal_counter_reset_is_recorded_before_status_filter(self) -> None:
        condition = {
            "type": "goal",
            "threadId": "t",
            "statuses": ["complete"],
            "tokensUsedEvery": 1000,
        }
        job = {"lastTokensUsedBucket": 4}
        goal = {"tokensUsed": 250, "status": "active"}

        class App:
            async def request(self, method, params):
                return {"goal": goal}

        ready, updates, reason = asyncio.run(
            conditions.goal_condition_ready(App(), condition, job)
        )

        self.assertFalse(ready)
        self.assertEqual(updates["lastTokensUsedBucket"], 0)
        self.assertEqual(reason, "goal usage counters reset")

    def test_goal_watch_is_superseded_by_replacement(self) -> None:
        condition = {
            "type": "goal",
            "threadId": "t",
            "tokensUsedEvery": 1000,
            "goalCreatedAt": 10,
        }
        job = {"lastTokensUsedBucket": 4}
        goal = {"tokensUsed": 5250, "status": "active", "createdAt": 20}

        class App:
            async def request(self, method, params):
                return {"goal": goal}

        ready, updates, reason = asyncio.run(
            conditions.goal_condition_ready(App(), condition, job)
        )

        self.assertFalse(ready)
        self.assertEqual(updates["status"], "superseded")
        self.assertEqual(reason, "watched goal was replaced")

    def test_stop_condition_detects_same_turn_becoming_terminal(self) -> None:
        class App:
            def __init__(self, turns: list[dict[str, str]]):
                self.turns = turns

            async def request(self, method, params):
                self.assert_request(method, params)
                return {"data": self.turns}

            def assert_request(self, method, params):
                if method != "thread/turns/list":
                    raise AssertionError(f"unexpected method: {method}")

        condition = asyncio.run(
            conditions.seed_stop_condition(
                App([{"id": "turn-1", "status": "inProgress"}]),
                {"type": "stop", "threadId": "t"},
            )
        )
        ready, updates, reason = asyncio.run(
            conditions.stop_condition_ready(
                App([{"id": "turn-1", "status": "completed"}]),
                condition,
            )
        )

        self.assertTrue(ready)
        self.assertEqual(updates["condition"]["cursorTurnStatus"], "completed")
        self.assertEqual(reason, "turn turn-1 completed")

    def test_exact_stop_condition_accepts_an_already_terminal_turn(self) -> None:
        class App:
            async def request(self, method, params):
                return {
                    "data": [{"id": "turn-1", "status": "completed"}],
                    "nextCursor": None,
                }

        condition = asyncio.run(
            conditions.seed_stop_condition(
                App(),
                {"type": "stop", "threadId": "t", "turnId": "latest"},
            )
        )
        ready, updates, reason = asyncio.run(
            conditions.stop_condition_ready(App(), condition)
        )

        self.assertEqual(condition["turnId"], "turn-1")
        self.assertNotIn("cursorTurnId", condition)
        self.assertTrue(ready)
        self.assertEqual(updates, {})
        self.assertEqual(reason, "turn turn-1 completed")

    def test_exact_stop_condition_waits_for_its_turn(self) -> None:
        class App:
            def __init__(self, status: str):
                self.status = status

            async def request(self, method, params):
                return {
                    "data": [{"id": "turn-1", "status": self.status}],
                    "nextCursor": None,
                }

        condition = {"type": "stop", "threadId": "t", "turnId": "turn-1"}
        ready, updates, reason = asyncio.run(
            conditions.stop_condition_ready(App("inProgress"), condition)
        )
        self.assertFalse(ready)
        self.assertEqual(updates, {})
        self.assertEqual(reason, "turn turn-1 is inProgress")

        ready, _, reason = asyncio.run(
            conditions.stop_condition_ready(App("interrupted"), condition)
        )
        self.assertTrue(ready)
        self.assertEqual(reason, "turn turn-1 interrupted")

    def test_exact_stop_seed_rejects_unknown_turn(self) -> None:
        class App:
            async def request(self, method, params):
                return {
                    "data": [{"id": "other", "status": "completed"}],
                    "nextCursor": None,
                }

        with self.assertRaisesRegex(WakectlError, "turn not found: missing"):
            asyncio.run(
                conditions.seed_stop_condition(
                    App(),
                    {"type": "stop", "threadId": "t", "turnId": "missing"},
                )
            )

    def test_stop_condition_detects_turn_completed_between_polls(self) -> None:
        class App:
            def __init__(self, turns: list[dict[str, str]]):
                self.turns = turns

            async def request(self, method, params):
                return {"data": self.turns}

        condition = {
            "type": "stop",
            "threadId": "t",
            "cursorTurnId": "turn-1",
            "cursorTurnStatus": "completed",
        }
        ready, updates, reason = asyncio.run(
            conditions.stop_condition_ready(
                App(
                    [
                        {"id": "turn-2", "status": "completed"},
                        {"id": "turn-1", "status": "completed"},
                    ]
                ),
                condition,
            )
        )

        self.assertTrue(ready)
        self.assertEqual(updates["condition"]["cursorTurnId"], "turn-2")
        self.assertEqual(reason, "turn turn-2 completed")

    def test_stop_condition_coalesces_completed_turn_before_new_active_turn(self) -> None:
        class App:
            async def request(self, method, params):
                return {
                    "data": [
                        {"id": "turn-3", "status": "inProgress"},
                        {"id": "turn-2", "status": "completed"},
                        {"id": "turn-1", "status": "completed"},
                    ]
                }

        condition = {
            "type": "stop",
            "threadId": "t",
            "repeat": True,
            "cursorTurnId": "turn-1",
            "cursorTurnStatus": "completed",
        }

        ready, updates, reason = asyncio.run(conditions.stop_condition_ready(App(), condition))

        self.assertTrue(ready)
        self.assertEqual(reason, "turn turn-2 completed")
        self.assertEqual(updates["condition"]["cursorTurnId"], "turn-3")
        self.assertEqual(updates["condition"]["cursorTurnStatus"], "inProgress")
        self.assertTrue(conditions.condition_repeats(updates["condition"]))

    def test_stop_condition_seeds_without_firing_for_existing_turn(self) -> None:
        class App:
            async def request(self, method, params):
                return {"data": [{"id": "turn-1", "status": "completed"}]}

        ready, updates, reason = asyncio.run(
            conditions.stop_condition_ready(App(), {"type": "stop", "threadId": "t"})
        )
        self.assertFalse(ready)
        self.assertEqual(reason, "waiting for turn completion")
        self.assertEqual(updates["condition"]["cursorTurnId"], "turn-1")

        ready, _, reason = asyncio.run(
            conditions.stop_condition_ready(App(), updates["condition"])
        )
        self.assertFalse(ready)
        self.assertEqual(
            reason,
            "waiting for a later turn; cursor turn is completed",
        )

    def test_stop_condition_fires_for_first_turn_after_empty_seed(self) -> None:
        class App:
            def __init__(self, turns: list[dict[str, str]]):
                self.turns = turns

            async def request(self, method, params):
                return {"data": self.turns}

        condition = asyncio.run(
            conditions.seed_stop_condition(
                App([]),
                {"type": "stop", "threadId": "t"},
            )
        )
        ready, updates, reason = asyncio.run(
            conditions.stop_condition_ready(
                App([{"id": "turn-1", "status": "completed"}]),
                condition,
            )
        )

        self.assertTrue(ready)
        self.assertEqual(reason, "turn turn-1 completed")
        self.assertEqual(updates["condition"]["cursorTurnId"], "turn-1")

    def test_stop_condition_fails_when_cursor_disappears(self) -> None:
        class App:
            async def request(self, method, params):
                return {
                    "data": [{"id": "older", "status": "completed"}],
                    "nextCursor": None,
                }

        ready, updates, reason = asyncio.run(
            conditions.stop_condition_ready(
                App(),
                {
                    "type": "stop",
                    "threadId": "t",
                    "cursorTurnId": "missing",
                    "cursorTurnStatus": "inProgress",
                },
            )
        )
        self.assertFalse(ready)
        self.assertEqual(updates["status"], "failed")
        self.assertIn("missing", reason)

    def test_stop_max_fires_requires_repeat(self) -> None:
        args = argparse.Namespace(thread_id="thread", repeat=False, max_fires=2)
        with self.assertRaises(WakectlError):
            conditions.build_stop_condition(args)

    def test_exact_stop_rejects_repeat(self) -> None:
        args = argparse.Namespace(
            thread_id="thread",
            turn="turn-1",
            repeat=True,
            max_fires=None,
        )
        with self.assertRaisesRegex(WakectlError, "--turn cannot be combined"):
            conditions.build_stop_condition(args)

    def test_max_fires_reached(self) -> None:
        condition = {
            "type": "stop",
            "threadId": "t",
            "repeat": True,
            "maxFires": 2,
        }
        self.assertFalse(conditions.max_fires_reached(condition, 1))
        self.assertTrue(conditions.max_fires_reached(condition, 2))

    def test_cmd_condition_timeout(self) -> None:
        condition = {
            "type": "cmd",
            "argv": [sys.executable, "-c", "import time; time.sleep(1)"],
        }

        ready, updates, reason = conditions.cmd_condition_ready(condition, timeout=0.01)

        self.assertFalse(ready)
        self.assertEqual(updates, {})
        self.assertEqual(reason, "command timed out after 0.01s")

    def test_wait_max_wait_bounds_slow_predicate(self) -> None:
        args = argparse.Namespace(
            condition_builder=lambda _: {
                "type": "cmd",
                "argv": [sys.executable, "-c", "import time; time.sleep(1)"],
            },
            max_wait=0.05,
            timeout=1.0,
            endpoint="unix://",
            poll_interval=0.01,
            json=True,
        )

        started = time.monotonic()
        with contextlib.redirect_stdout(io.StringIO()):
            result = asyncio.run(commands.cmd_wait(args))
        elapsed = time.monotonic() - started

        self.assertEqual(result, 1)
        self.assertLess(elapsed, 0.5)

    def test_wait_max_wait_includes_agent_path_resolution(self) -> None:
        class FakeAppServer:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args: object) -> None:
                return None

        async def slow_resolution(*args: object, **kwargs: object) -> None:
            await asyncio.sleep(1)

        args = argparse.Namespace(
            thread_id="/root/worker",
            tree="root-thread",
            condition_builder=lambda _: {
                "type": "goal",
                "threadId": "worker",
                "statuses": ["complete"],
            },
            max_wait=0.05,
            timeout=1.0,
            endpoint="unix://",
            poll_interval=0.01,
            json=True,
        )

        started = time.monotonic()
        with (
            mock.patch.object(
                commands,
                "wakectl_appserver",
                return_value=FakeAppServer(),
            ),
            mock.patch.object(
                commands,
                "resolve_condition_reference",
                slow_resolution,
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            result = asyncio.run(commands.cmd_wait(args))
        elapsed = time.monotonic() - started

        self.assertEqual(result, 1)
        self.assertLess(elapsed, 0.5)

    def test_wait_reconnects_for_each_appserver_poll(self) -> None:
        opened = 0
        closed = 0

        class FakeAppServer:
            async def __aenter__(self):
                nonlocal opened
                opened += 1
                return self

            async def __aexit__(self, *args: object) -> None:
                nonlocal closed
                closed += 1

        args = argparse.Namespace(
            condition_builder=lambda _: {
                "type": "goal",
                "threadId": "worker",
                "statuses": ["complete"],
            },
            max_wait=None,
            timeout=1.0,
            endpoint="unix://",
            poll_interval=0.01,
            json=True,
        )
        checks = mock.AsyncMock(
            side_effect=[
                (False, {}, "status is active"),
                (True, {}, "goal predicate matched"),
            ]
        )

        with (
            mock.patch.object(
                commands,
                "wakectl_appserver",
                side_effect=lambda *args: FakeAppServer(),
            ),
            mock.patch.object(commands, "condition_ready", checks),
            mock.patch.object(commands.asyncio, "sleep", mock.AsyncMock()),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            result = asyncio.run(commands.cmd_wait(args))

        self.assertEqual(result, 0)
        self.assertEqual((opened, closed), (2, 2))

    def test_state_database_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            job = conditions.new_job(
                {"type": "time", "at": parsing.now_seconds() + 60},
                "thread",
                input_action("message", allow_active=True),
                "unix://",
                timeout=45.0,
            )

            state.insert_job(path, job)
            jobs = state.list_jobs(path)

            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0]["id"], job["id"])
            self.assertEqual(jobs[0]["condition"]["type"], "time")
            self.assertTrue(jobs[0]["action"]["allowActive"])
            self.assertEqual(jobs[0]["timeout"], 45.0)

    def test_cmd_add_time_job_persists_cli_policy_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            args = parser.build_parser().parse_args(
                [
                    "--endpoint",
                    "unix://custom.sock",
                    "add",
                    "time",
                    "--after",
                    "1s",
                    "--to",
                    "target-thread",
                    "--allow-active",
                    "wake message",
                    "--timeout",
                    "45",
                    "--state",
                    str(path),
                ]
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = asyncio.run(args.func(args))

            self.assertEqual(rc, 0)
            self.assertRegex(stdout.getvalue().strip(), r"^[0-9a-f]{12}$")
            jobs = state.list_jobs(path)
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0]["condition"]["type"], "time")
            self.assertEqual(jobs[0]["targetThreadId"], "target-thread")
            self.assertEqual(jobs[0]["action"]["message"], "wake message")
            expected_socket = Path.cwd() / "custom.sock"
            self.assertEqual(jobs[0]["endpoint"], f"unix://{expected_socket}")
            self.assertTrue(jobs[0]["action"]["allowActive"])
            self.assertEqual(jobs[0]["timeout"], 45.0)

    def test_add_resolves_agent_paths_once_before_persisting(self) -> None:
        class FakeAppServer:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args: object) -> None:
                return None

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            args = parser.build_parser().parse_args(
                [
                    "add",
                    "goal",
                    "/root/worker",
                    "--status",
                    "complete",
                    "--to",
                    "/root",
                    "worker complete",
                    "--tree",
                    "root-thread",
                    "--state",
                    str(path),
                ]
            )

            with (
                mock.patch.object(
                    commands,
                    "wakectl_appserver",
                    return_value=FakeAppServer(),
                ),
                mock.patch.object(
                    commands,
                    "resolve_thread_reference",
                    mock.AsyncMock(return_value="worker-thread"),
                ) as resolve_condition,
                mock.patch.object(
                    commands,
                    "resolve_agent_path",
                    mock.AsyncMock(
                        return_value={
                            "threadId": "root-thread",
                            "inputOwner": "direct",
                        }
                    ),
                ) as resolve_target,
                mock.patch.object(commands, "seed_goal_job", mock.AsyncMock()),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(asyncio.run(args.func(args)), 0)

            stored = state.list_jobs(path)[0]
            self.assertEqual(stored["condition"]["threadId"], "worker-thread")
            self.assertEqual(stored["targetThreadId"], "root-thread")
            resolve_condition.assert_awaited_once_with(
                mock.ANY,
                "/root/worker",
                tree_thread_id="root-thread",
            )
            resolve_target.assert_awaited_once_with(
                mock.ANY,
                "/root",
                tree_thread_id="root-thread",
            )

    def test_add_rejects_parent_owned_agent_path_as_delivery_target(self) -> None:
        class FakeAppServer:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args: object) -> None:
                return None

        args = parser.build_parser().parse_args(
            [
                "add",
                "time",
                "--after",
                "1m",
                "--to",
                "/root/worker",
                "wake",
                "--tree",
                "root-thread",
            ]
        )
        with (
            mock.patch.object(
                commands,
                "wakectl_appserver",
                return_value=FakeAppServer(),
            ),
            mock.patch.object(
                commands,
                "resolve_agent_path",
                mock.AsyncMock(
                    return_value={
                        "threadId": "worker-thread",
                        "inputOwner": "parent",
                    }
                ),
            ),
        ):
            with self.assertRaisesRegex(
                WakectlError,
                "cannot receive scheduled input",
            ):
                asyncio.run(args.func(args))

    def test_wait_resolves_agent_path_before_evaluating_condition(self) -> None:
        class FakeAppServer:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args: object) -> None:
                return None

        args = parser.build_parser().parse_args(
            [
                "wait",
                "goal",
                "/root/worker",
                "--status",
                "complete",
                "--tree",
                "root-thread",
                "--max-wait",
                "1m",
            ]
        )
        ready = mock.AsyncMock(return_value=(True, {}, "goal predicate matched"))
        with (
            mock.patch.object(
                commands,
                "wakectl_appserver",
                return_value=FakeAppServer(),
            ),
            mock.patch.object(
                commands,
                "resolve_thread_reference",
                mock.AsyncMock(return_value="worker-thread"),
            ) as resolve,
            mock.patch.object(commands, "condition_ready", ready),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(asyncio.run(args.func(args)), 0)

        resolve.assert_awaited_once_with(
            mock.ANY,
            "/root/worker",
            tree_thread_id="root-thread",
        )
        self.assertEqual(ready.await_args.args[1]["threadId"], "worker-thread")

    def test_cmd_add_stop_seeds_persisted_turn_cursor(self) -> None:
        class FakeAppServer:
            def __init__(self, endpoint: str, timeout: float, **kwargs: object) -> None:
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args: object) -> None:
                return None

            async def request(self, method: str, params=None):
                if method == "thread/turns/list":
                    return {"data": [{"id": "turn-1", "status": "inProgress"}]}
                raise AssertionError(f"unexpected method: {method}")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            args = parser.build_parser().parse_args(
                [
                    "add",
                    "stop",
                    "worker",
                    "--to",
                    "main",
                    "worker stopped",
                    "--state",
                    str(path),
                ]
            )

            with (
                mock.patch.object(commands, "AppServer", FakeAppServer),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(asyncio.run(args.func(args)), 0)

            condition = state.list_jobs(path)[0]["condition"]
            self.assertEqual(condition["cursorTurnId"], "turn-1")
            self.assertEqual(condition["cursorTurnStatus"], "inProgress")

    def test_cmd_add_stop_resolves_latest_exact_turn(self) -> None:
        class FakeAppServer:
            def __init__(self, endpoint: str, timeout: float, **kwargs: object) -> None:
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args: object) -> None:
                return None

            async def request(self, method: str, params=None):
                if method == "thread/turns/list":
                    return {"data": [{"id": "turn-1", "status": "completed"}]}
                raise AssertionError(f"unexpected method: {method}")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            args = parser.build_parser().parse_args(
                [
                    "add",
                    "stop",
                    "worker",
                    "--turn",
                    "latest",
                    "--to",
                    "main",
                    "worker stopped",
                    "--state",
                    str(path),
                ]
            )

            with (
                mock.patch.object(commands, "AppServer", FakeAppServer),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(asyncio.run(args.func(args)), 0)

            condition = state.list_jobs(path)[0]["condition"]
            self.assertEqual(condition["turnId"], "turn-1")
            self.assertNotIn("cursorTurnId", condition)

    def test_cmd_add_goal_does_not_persist_after_seed_failure(self) -> None:
        class BrokenAppServer:
            async def __aenter__(self):
                raise ThreadctlError("goal unavailable")

            async def __aexit__(self, *args: object) -> None:
                return None

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            args = parser.build_parser().parse_args(
                [
                    "add",
                    "goal",
                    "worker",
                    "--status",
                    "complete",
                    "--to",
                    "main",
                    "worker complete",
                    "--state",
                    str(path),
                ]
            )

            with mock.patch.object(
                commands,
                "wakectl_appserver",
                return_value=BrokenAppServer(),
            ):
                with self.assertRaisesRegex(ThreadctlError, "goal unavailable"):
                    asyncio.run(args.func(args))

            self.assertFalse(path.exists())

    def test_cancel_only_changes_pending_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            job = conditions.new_job(
                {"type": "time", "at": parsing.now_seconds() + 60},
                "thread",
                input_action("message"),
                "unix://",
            )
            state.insert_job(path, job)
            owner, _ = state.claim_pending_jobs(path, 60)
            self.assertTrue(
                state.update_claimed_job(
                    path,
                    job["id"],
                    owner,
                    {"status": "fired", "firedAt": parsing.now_seconds()},
                )
            )

            self.assertFalse(state.cancel_job(path, job["id"]))
            self.assertEqual(state.list_jobs(path, include_all=True)[0]["status"], "fired")

    def test_cancel_refuses_job_claimed_by_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            job = conditions.new_job(
                {"type": "time", "at": parsing.now_seconds() + 60},
                "thread",
                input_action("message"),
                "unix://",
            )
            state.insert_job(path, job)
            state.claim_pending_jobs(path, 60)

            self.assertFalse(state.cancel_job(path, job["id"]))
            self.assertEqual(state.list_jobs(path)[0]["status"], "pending")

    def test_text_list_prefers_current_error_over_prior_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            job = conditions.new_job(
                {"type": "time", "at": parsing.now_seconds() + 60},
                "thread",
                input_action("message"),
                "unix://",
            )
            state.insert_job(path, job)
            owner, _ = state.claim_pending_jobs(path, 60)
            self.assertTrue(
                state.update_claimed_job(
                    path,
                    job["id"],
                    owner,
                    {"lastReason": "waiting", "lastError": "socket unavailable"},
                )
            )
            args = argparse.Namespace(state=path, all=False, json=False)
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                self.assertEqual(commands.cmd_list(args), 0)

            self.assertIn("socket unavailable", stdout.getvalue())
            self.assertNotIn("waiting", stdout.getvalue())

    def test_state_database_migrates_existing_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            conn = sqlite3.connect(path)
            conn.executescript(
                """
                CREATE TABLE jobs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    condition_json TEXT NOT NULL,
                    target_thread_id TEXT NOT NULL,
                    message TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    fired_at INTEGER,
                    fire_count INTEGER NOT NULL DEFAULT 0,
                    last_fired_at INTEGER,
                    last_turn_id TEXT,
                    last_reason TEXT,
                    last_error TEXT,
                    last_tokens_used_bucket INTEGER,
                    last_time_used_bucket INTEGER,
                    lease_owner TEXT,
                    lease_started_at INTEGER,
                    lease_until INTEGER
                );
                INSERT INTO jobs (
                    id, status, condition_json, target_thread_id, message, endpoint,
                    created_at, updated_at, fire_count
                )
                VALUES (
                    'oldjob', 'pending', '{"type": "time", "at": 1}',
                    'thread', 'message', 'unix://', 1, 1, 0
                );
                """
            )
            conn.close()

            jobs = state.list_jobs(path)

            self.assertEqual(jobs[0]["id"], "oldjob")
            self.assertEqual(
                jobs[0]["action"],
                {"type": "input", "message": "message", "legacy": True},
            )
            self.assertNotIn("timeout", jobs[0])

    def test_default_state_permissions_are_private(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            state_dir = state_root / "codex-wakectl"
            state_dir.mkdir(parents=True)
            state_dir.chmod(0o775)
            path = state_dir / "jobs.sqlite3"
            path.touch()
            path.chmod(0o644)

            with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(state_root)}):
                conn = state.open_state(state.default_state_path())
                conn.close()

            self.assertEqual(state_dir.stat().st_mode & 0o777, 0o700)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_existing_custom_state_permissions_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "shared"
            state_dir.mkdir()
            state_dir.chmod(0o755)
            path = state_dir / "jobs.sqlite3"
            path.touch()
            path.chmod(0o640)

            conn = state.open_state(path)
            conn.close()

            self.assertEqual(state_dir.stat().st_mode & 0o777, 0o755)
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)

    def test_claimed_jobs_are_released_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            job = conditions.new_job(
                {"type": "time", "at": parsing.now_seconds() + 60},
                "thread",
                input_action("message"),
                "unix://",
            )
            state.insert_job(path, job)

            owner, jobs = state.claim_pending_jobs(path, 60)
            self.assertEqual([claimed["id"] for claimed in jobs], [job["id"]])

            _, overlapping = state.claim_pending_jobs(path, 60)
            self.assertEqual(overlapping, [])

            self.assertTrue(
                state.update_claimed_job(
                    path,
                    job["id"],
                    owner,
                    {"lastReason": "waiting"},
                )
            )
            stored = state.list_jobs(path)[0]
            self.assertEqual(stored["lastReason"], "waiting")
            self.assertNotIn("leaseOwner", stored)

            _, reclaimed = state.claim_pending_jobs(path, 60)
            self.assertEqual([claimed["id"] for claimed in reclaimed], [job["id"]])

    def test_claim_limit_only_claims_limited_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            first = conditions.new_job(
                {"type": "time", "at": parsing.now_seconds() + 60},
                "first",
                input_action("message"),
                "unix://",
            )
            second = conditions.new_job(
                {"type": "time", "at": parsing.now_seconds() + 60},
                "second",
                input_action("message"),
                "unix://",
            )
            state.insert_job(path, first)
            state.insert_job(path, second)

            _, claimed = state.claim_pending_jobs(path, 60, limit=1)
            self.assertEqual(len(claimed), 1)

            _, next_claimed = state.claim_pending_jobs(path, 60, limit=1)
            self.assertEqual(len(next_claimed), 1)
            self.assertNotEqual(claimed[0]["id"], next_claimed[0]["id"])

    def test_systemd_units_run_queue_once(self) -> None:
        service, timer = systemd.build_systemd_units(
            wakectl_bin="/usr/local/bin/codex-wakectl",
            state=Path("/tmp/wake jobs.sqlite3"),
            interval_seconds=30,
        )

        self.assertIn(
            'ExecStart=/usr/local/bin/codex-wakectl --state "/tmp/wake jobs.sqlite3" run',
            service,
        )
        self.assertIn("OnActiveSec=30s", timer)
        self.assertIn("OnUnitInactiveSec=30s", timer)


if __name__ == "__main__":
    unittest.main()
