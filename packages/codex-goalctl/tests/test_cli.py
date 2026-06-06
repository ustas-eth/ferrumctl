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
        with self.assertRaises(argparse.ArgumentTypeError):
            cli.positive_float("0")

    def test_parser_rejects_negative_timeout(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                cli.build_parser().parse_args(["--timeout", "-1", "get", "thread"])


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
        )

        with mock.patch.object(cli, "connect_appserver") as connect:
            with self.assertRaises(cli.GoalctlError):
                cli.cmd_update(args)

        connect.assert_not_called()

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
