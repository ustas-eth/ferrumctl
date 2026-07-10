from __future__ import annotations

import argparse
import contextlib
import io
import unittest
from unittest import mock

from codex_goalctl import cli


class ParseTests(unittest.TestCase):
    def test_timeout_must_be_positive(self) -> None:
        self.assertEqual(cli.positive_float("1.5"), 1.5)
        for value in ("0", "nan", "inf", "-inf"):
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    cli.positive_float(value)

    def test_parser_rejects_negative_timeout(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                cli.build_parser().parse_args(["--timeout", "-1", "get", "thread"])

    def test_token_budget_update_options_are_mutually_exclusive(self) -> None:
        args = cli.build_parser().parse_args(
            ["update", "thread", "--clear-token-budget"]
        )
        self.assertTrue(args.clear_token_budget)

        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                cli.build_parser().parse_args(
                    [
                        "update",
                        "thread",
                        "--token-budget",
                        "1000",
                        "--clear-token-budget",
                    ]
                )

    def test_common_options_work_after_subcommand_arguments(self) -> None:
        args = cli.build_parser().parse_args(
            ["replace", "thread", "objective", "--json", "--timeout", "5"]
        )
        self.assertTrue(args.json)
        self.assertEqual(args.timeout, 5)

    def test_version(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaisesRegex(SystemExit, "0"):
                cli.build_parser().parse_args(["--version"])
        self.assertEqual(output.getvalue(), "codex-goalctl 0.1.0\n")


class FakeApp:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.closed = False

    def request(self, method: str, params: dict) -> dict:
        self.calls.append((method, params))
        if method == "thread/goal/clear":
            return {"cleared": True}
        if method == "thread/goal/set":
            goal = {
                "objective": params.get("objective", "existing objective"),
                "status": params.get("status", "active"),
            }
            if "tokenBudget" in params:
                goal["tokenBudget"] = params["tokenBudget"]
            return {"goal": goal}
        raise AssertionError(f"unexpected method: {method}")

    def close(self) -> None:
        self.closed = True


class GoalCommandTests(unittest.TestCase):
    def test_replace_clears_before_setting_fresh_active_goal(self) -> None:
        app = FakeApp()
        args = argparse.Namespace(
            thread_id="00000000-0000-4000-8000-000000000001",
            objective="new objective",
            status=None,
            token_budget=1000,
            clear_token_budget=False,
            json=False,
        )

        with mock.patch.object(cli, "connect_appserver", return_value=app):
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = cli.cmd_replace(args)

        self.assertEqual(rc, 0)
        self.assertEqual(
            app.calls,
            [
                (
                    "thread/goal/clear",
                    {"threadId": "00000000-0000-4000-8000-000000000001"},
                ),
                (
                    "thread/goal/set",
                    {
                        "threadId": "00000000-0000-4000-8000-000000000001",
                        "objective": "new objective",
                        "status": "active",
                        "tokenBudget": 1000,
                    },
                ),
            ],
        )
        self.assertTrue(app.closed)
        self.assertEqual(stdout.getvalue(), "active\tnew objective\n")

    def test_update_only_sends_supplied_goal_fields(self) -> None:
        app = FakeApp()
        args = argparse.Namespace(
            thread_id="00000000-0000-4000-8000-000000000001",
            objective=None,
            status="paused",
            token_budget=None,
            clear_token_budget=False,
            json=False,
        )

        with mock.patch.object(cli, "connect_appserver", return_value=app):
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = cli.cmd_update(args)

        self.assertEqual(rc, 0)
        self.assertEqual(
            app.calls,
            [
                (
                    "thread/goal/set",
                    {
                        "threadId": "00000000-0000-4000-8000-000000000001",
                        "status": "paused",
                    },
                )
            ],
        )
        self.assertTrue(app.closed)
        self.assertEqual(stdout.getvalue(), "paused\texisting objective\n")

    def test_update_rejects_noop_before_connecting_appserver(self) -> None:
        args = argparse.Namespace(
            objective=None,
            status=None,
            token_budget=None,
            clear_token_budget=False,
        )

        with mock.patch.object(cli, "connect_appserver") as connect:
            with self.assertRaises(cli.GoalctlError):
                cli.cmd_update(args)

        connect.assert_not_called()

    def test_update_can_clear_token_budget(self) -> None:
        app = FakeApp()
        args = argparse.Namespace(
            thread_id="00000000-0000-4000-8000-000000000001",
            objective=None,
            status=None,
            token_budget=None,
            clear_token_budget=True,
            json=False,
        )

        with mock.patch.object(cli, "connect_appserver", return_value=app):
            with contextlib.redirect_stdout(io.StringIO()):
                rc = cli.cmd_update(args)

        self.assertEqual(rc, 0)
        self.assertEqual(
            app.calls,
            [
                (
                    "thread/goal/set",
                    {
                        "threadId": "00000000-0000-4000-8000-000000000001",
                        "tokenBudget": None,
                    },
                )
            ],
        )

    def test_clear_prints_json_result(self) -> None:
        args = argparse.Namespace(
            thread_id="00000000-0000-4000-8000-000000000001",
            json=True,
        )

        with mock.patch.object(
            cli,
            "appserver_request",
            return_value={"cleared": True},
        ) as request:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = cli.cmd_clear(args)

        self.assertEqual(rc, 0)
        request.assert_called_once_with(
            args,
            "thread/goal/clear",
            {"threadId": "00000000-0000-4000-8000-000000000001"},
        )
        self.assertIn('"cleared": true', stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
