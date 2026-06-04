from __future__ import annotations

import argparse
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from codex_wakectl import cli


class ParseTests(unittest.TestCase):
    def test_parse_duration(self) -> None:
        self.assertEqual(cli.parse_duration("10s"), 10)
        self.assertEqual(cli.parse_duration("5m"), 300)
        self.assertEqual(cli.parse_duration("2h"), 7200)
        self.assertEqual(cli.parse_duration("1d"), 86400)
        self.assertEqual(cli.parse_duration("1_000s"), 1000)

    def test_parse_duration_rejects_missing_unit(self) -> None:
        with self.assertRaises(argparse.ArgumentTypeError):
            cli.parse_duration("300")

    def test_parse_tokens_are_plain_integers(self) -> None:
        self.assertEqual(cli.parse_positive_int("3000000"), 3000000)
        self.assertEqual(cli.parse_positive_int("3_000_000"), 3000000)

    def test_parse_statuses(self) -> None:
        self.assertEqual(
            cli.parse_statuses("complete,budgetLimited"),
            ["complete", "budgetLimited"],
        )
        with self.assertRaises(argparse.ArgumentTypeError):
            cli.parse_statuses("done")

    def test_wait_options_after_condition(self) -> None:
        args = cli.build_parser().parse_args(
            ["wait", "time", "--after", "1s", "--max-wait", "2s"]
        )
        self.assertEqual(args.after, 1)
        self.assertEqual(args.max_wait, 2)

    def test_add_globals_after_condition(self) -> None:
        args = cli.build_parser().parse_args(
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

    def test_run_replaces_tick(self) -> None:
        args = cli.build_parser().parse_args(["run", "--limit", "1"])
        self.assertEqual(args.limit, 1)
        self.assertIs(args.func, cli.cmd_run)

        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                cli.build_parser().parse_args(["tick"])

    def test_systemd_install_options(self) -> None:
        args = cli.build_parser().parse_args(["systemd", "install", "--interval", "5m"])
        self.assertEqual(args.interval, 300)
        self.assertIs(args.func, cli.cmd_systemd_install)


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
        with self.assertRaises(cli.WakectlError):
            cli.build_goal_condition(args)

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
        with self.assertRaises(cli.WakectlError):
            cli.build_goal_condition(args)

    def test_goal_repeating_bucket(self) -> None:
        condition = {"type": "goal", "threadId": "t", "tokensUsedEvery": 3000000}
        job = {"lastTokensUsedBucket": 1}
        goal = {"tokensUsed": 6200000, "status": "active"}

        class App:
            async def request(self, method, params):
                return {"goal": goal}

        ready, updates, _ = cli.asyncio.run(cli.goal_condition_ready(App(), condition, job))
        self.assertTrue(ready)
        self.assertEqual(updates["lastTokensUsedBucket"], 2)

    def test_state_database_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            job = cli.new_job(
                {"type": "time", "at": cli.now_seconds() + 60},
                "thread",
                "message",
                "unix://",
            )

            cli.insert_job(path, job)
            jobs = cli.list_jobs(path)

            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0]["id"], job["id"])
            self.assertEqual(jobs[0]["condition"]["type"], "time")

    def test_claimed_jobs_are_released_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            job = cli.new_job(
                {"type": "time", "at": cli.now_seconds() + 60},
                "thread",
                "message",
                "unix://",
            )
            cli.insert_job(path, job)

            owner, jobs = cli.claim_pending_jobs(path, 60)
            self.assertEqual([claimed["id"] for claimed in jobs], [job["id"]])

            _, overlapping = cli.claim_pending_jobs(path, 60)
            self.assertEqual(overlapping, [])

            self.assertTrue(
                cli.update_claimed_job(
                    path,
                    job["id"],
                    owner,
                    {"lastReason": "waiting"},
                )
            )
            stored = cli.list_jobs(path)[0]
            self.assertEqual(stored["lastReason"], "waiting")
            self.assertNotIn("leaseOwner", stored)

            _, reclaimed = cli.claim_pending_jobs(path, 60)
            self.assertEqual([claimed["id"] for claimed in reclaimed], [job["id"]])

    def test_systemd_units_run_queue_once(self) -> None:
        service, timer = cli.build_systemd_units(
            wakectl_bin="/usr/local/bin/codex-wakectl",
            state=Path("/tmp/wake jobs.sqlite3"),
            interval_seconds=30,
        )

        self.assertIn(
            'ExecStart=/usr/local/bin/codex-wakectl --state "/tmp/wake jobs.sqlite3" run',
            service,
        )
        self.assertIn("OnUnitActiveSec=30s", timer)


if __name__ == "__main__":
    unittest.main()
