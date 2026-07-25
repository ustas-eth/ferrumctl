from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import unittest
from unittest import mock

from codex_limitctl import cli


PAYLOAD = {
    "rateLimits": {
        "limitId": "codex",
        "primary": {
            "usedPercent": 11,
            "windowDurationMins": 10080,
            "resetsAt": 1784959243,
        },
    },
    "rateLimitsByLimitId": {
        "codex": {
            "limitId": "codex",
            "planType": "pro",
            "primary": {
                "usedPercent": 11,
                "windowDurationMins": 10080,
                "resetsAt": 1784959243,
            },
            "secondary": None,
        }
    },
    "rateLimitResetCredits": {
        "availableCount": 3,
        "credits": [{"id": "must-not-appear"}],
    },
}


class ParseTests(unittest.TestCase):
    def test_parses_window_durations(self) -> None:
        self.assertEqual(cli.window_duration("5h"), 300)
        self.assertEqual(cli.window_duration("7d"), 10080)
        self.assertEqual(cli.window_duration("1d12h"), 2160)

    def test_window_duration_requires_whole_minutes(self) -> None:
        for value in ("30s", "5", "0m", "1h2d"):
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    cli.window_duration(value)

    def test_percentage_accepts_optional_percent_sign(self) -> None:
        self.assertEqual(cli.percentage("20"), 20)
        self.assertEqual(cli.percentage("20%"), 20)
        for value in ("-1", "101", "1.5"):
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    cli.percentage(value)

    def test_common_options_work_after_subcommand(self) -> None:
        args = cli.build_parser().parse_args(
            ["list", "codex", "--window", "7d", "--json", "--timeout", "5"]
        )
        self.assertTrue(args.json)
        self.assertEqual(args.timeout, 5)

    def test_global_json_is_preserved_for_rollout_commands(self) -> None:
        args = cli.build_parser().parse_args(["--json", "activity"])
        self.assertTrue(args.json)

    def test_invalid_environment_timeout_is_parser_error(self) -> None:
        with mock.patch.dict(os.environ, {"CODEX_LIMITCTL_TIMEOUT": "bogus"}):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    cli.build_parser().parse_args(["list"])
        self.assertEqual(raised.exception.code, 2)

    def test_help_ignores_invalid_environment_timeout(self) -> None:
        with mock.patch.dict(os.environ, {"CODEX_LIMITCTL_TIMEOUT": "bogus"}):
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    cli.build_parser().parse_args(["--help"])
        self.assertEqual(raised.exception.code, 0)

    def test_explicit_timeout_overrides_invalid_environment_default(self) -> None:
        with mock.patch.dict(os.environ, {"CODEX_LIMITCTL_TIMEOUT": "bogus"}):
            args = cli.build_parser().parse_args(["list", "--timeout", "5"])
        self.assertEqual(args.timeout, 5)

    def test_test_requires_one_predicate(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                cli.build_parser().parse_args(["test", "codex", "--window", "7d"])

    def test_version(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaisesRegex(SystemExit, "0"):
                cli.build_parser().parse_args(["--version"])
        self.assertEqual(output.getvalue(), "codex-limitctl 0.2.4\n")


class CommandTests(unittest.TestCase):
    def run_command(self, argv: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(cli, "read_rate_limits", return_value=PAYLOAD):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                rc = cli.main(argv)
        return rc, stdout.getvalue(), stderr.getvalue()

    def test_list_prints_compact_window(self) -> None:
        rc, stdout, stderr = self.run_command(["list"])
        self.assertEqual(rc, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(
            stdout,
            "codex\tname=-\twindow=7d\tused=11%\tremaining=89%\t"
            "resets=2026-07-25T06:00:43Z\n",
        )

    def test_list_json_is_normalized_and_redacted(self) -> None:
        rc, stdout, _ = self.run_command(["list", "--json"])
        result = json.loads(stdout)

        self.assertEqual(rc, 0)
        self.assertEqual(result["windows"][0]["remainingPercent"], 89)
        self.assertNotIn("must-not-appear", stdout)
        self.assertNotIn("rateLimitResetCredits", stdout)

    def test_test_is_quiet_and_uses_exit_status(self) -> None:
        success = self.run_command(
            ["test", "codex", "--window", "7d", "--remaining-at-least", "20"]
        )
        failure = self.run_command(
            ["test", "codex", "--window", "7d", "--remaining-at-least", "90"]
        )

        self.assertEqual(success, (0, "", ""))
        self.assertEqual(failure, (1, "", ""))

    def test_test_supports_upper_threshold(self) -> None:
        rc, stdout, stderr = self.run_command(
            ["test", "codex", "--window", "7d", "--remaining-at-most", "90"]
        )
        self.assertEqual((rc, stdout, stderr), (0, "", ""))

    def test_test_json_prints_observation_and_predicate(self) -> None:
        rc, stdout, _ = self.run_command(
            [
                "test",
                "codex",
                "--window",
                "7d",
                "--remaining-at-least",
                "90",
                "--json",
            ]
        )
        result = json.loads(stdout)
        self.assertEqual(rc, 1)
        self.assertFalse(result["matched"])
        self.assertEqual(result["predicate"], {"remainingAtLeast": 90})

    def test_missing_window_is_error_not_false(self) -> None:
        rc, stdout, stderr = self.run_command(
            ["test", "codex", "--window", "5h", "--remaining-at-least", "20"]
        )
        self.assertEqual(rc, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(
            stderr,
            "codex-limitctl: codex has no reported 5h window\n",
        )

    def test_usage_prints_filtered_account_days(self) -> None:
        payload = {
            "dailyUsageBuckets": [
                {"startDate": "2026-07-18", "tokens": 10},
                {"startDate": "2026-07-20", "tokens": 20},
            ]
        }
        stdout = io.StringIO()
        with mock.patch.object(cli, "read_token_usage", return_value=payload):
            with contextlib.redirect_stdout(stdout):
                rc = cli.main(["usage", "--since", "2026-07-19"])

        self.assertEqual(rc, 0)
        self.assertEqual(stdout.getvalue(), "2026-07-20\ttokens=20\n")

    def test_history_filters_local_observations(self) -> None:
        rows = [
            {
                "observedAt": "2026-07-20T00:00:00Z",
                "threadId": "thread-1",
                "model": "gpt-test",
                "serviceTier": "default",
                "limitId": "codex",
                "windowDurationMins": 10080,
                "usedPercent": 20,
                "remainingPercent": 80,
                "resetsAt": 1800000000,
            }
        ]
        stdout = io.StringIO()
        with mock.patch.object(cli, "resolve_codex_home"):
            with mock.patch.object(cli, "scan_rollouts", return_value=(rows, [])):
                with contextlib.redirect_stdout(stdout):
                    rc = cli.main(
                        ["history", "codex", "--window", "7d", "--json"]
                    )

        result = json.loads(stdout.getvalue())
        self.assertEqual(rc, 0)
        self.assertEqual(result["scope"], "host-local")
        self.assertEqual(result["accountScope"], "unscoped")
        self.assertEqual(result["history"], rows)

    def test_activity_prints_largest_threads_first(self) -> None:
        rows = [
            {
                "threadId": "thread-1",
                "model": "gpt-test",
                "serviceTier": "default",
                "limitId": "codex",
                "updates": 2,
                "inputTokens": 90,
                "cachedInputTokens": 50,
                "outputTokens": 10,
                "reasoningOutputTokens": 4,
                "totalTokens": 100,
            }
        ]
        stdout = io.StringIO()
        with mock.patch.object(cli, "resolve_codex_home"):
            with mock.patch.object(cli, "scan_rollouts", return_value=([], rows)):
                with contextlib.redirect_stdout(stdout):
                    rc = cli.main(["activity"])

        self.assertEqual(rc, 0)
        self.assertIn("thread-1\tmodel=gpt-test", stdout.getvalue())
        self.assertIn("tokens=100", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
