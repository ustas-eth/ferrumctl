from __future__ import annotations

import argparse
import contextlib
import io
import sqlite3
import sys
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

    def test_parse_positive_float(self) -> None:
        self.assertEqual(cli.parse_positive_float("1.5"), 1.5)
        with self.assertRaises(argparse.ArgumentTypeError):
            cli.parse_positive_float("0")

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

    def test_add_stores_wake_policy_options(self) -> None:
        args = cli.build_parser().parse_args(
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

    def test_run_replaces_tick(self) -> None:
        args = cli.build_parser().parse_args(["run", "--limit", "1"])
        self.assertEqual(args.limit, 1)
        self.assertIs(args.func, cli.cmd_run)

        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                cli.build_parser().parse_args(["tick"])
            with self.assertRaises(SystemExit):
                cli.build_parser().parse_args(["run", "--allow-active"])

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

    def test_cmd_condition_timeout(self) -> None:
        condition = {
            "type": "cmd",
            "argv": [sys.executable, "-c", "import time; time.sleep(1)"],
        }

        ready, updates, reason = cli.cmd_condition_ready(condition, timeout=0.01)

        self.assertFalse(ready)
        self.assertEqual(updates, {})
        self.assertEqual(reason, "command timed out after 0.01s")

    def test_state_database_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            job = cli.new_job(
                {"type": "time", "at": cli.now_seconds() + 60},
                "thread",
                "message",
                "unix://",
                allow_active=True,
                timeout=45.0,
            )

            cli.insert_job(path, job)
            jobs = cli.list_jobs(path)

            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0]["id"], job["id"])
            self.assertEqual(jobs[0]["condition"]["type"], "time")
            self.assertTrue(jobs[0]["allowActive"])
            self.assertEqual(jobs[0]["timeout"], 45.0)

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

            jobs = cli.list_jobs(path)

            self.assertEqual(jobs[0]["id"], "oldjob")
            self.assertFalse(jobs[0]["allowActive"])
            self.assertNotIn("timeout", jobs[0])

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

    def test_claim_limit_only_claims_limited_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.sqlite3"
            first = cli.new_job(
                {"type": "time", "at": cli.now_seconds() + 60},
                "first",
                "message",
                "unix://",
            )
            second = cli.new_job(
                {"type": "time", "at": cli.now_seconds() + 60},
                "second",
                "message",
                "unix://",
            )
            cli.insert_job(path, first)
            cli.insert_job(path, second)

            _, claimed = cli.claim_pending_jobs(path, 60, limit=1)
            self.assertEqual(len(claimed), 1)

            _, next_claimed = cli.claim_pending_jobs(path, 60, limit=1)
            self.assertEqual(len(next_claimed), 1)
            self.assertNotEqual(claimed[0]["id"], next_claimed[0]["id"])

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
        self.assertIn("OnActiveSec=30s", timer)
        self.assertIn("OnUnitInactiveSec=30s", timer)


if __name__ == "__main__":
    unittest.main()
