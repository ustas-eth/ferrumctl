from __future__ import annotations

import argparse
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
                "/tmp/jobs.json",
            ]
        )
        self.assertEqual(str(args.state), "/tmp/jobs.json")


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

    def test_state_store_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.json"
            with cli.StateStore(path) as store:
                store.data["jobs"] = [{"id": "abc", "status": "pending"}]
                store.save()
            with cli.StateStore(path) as store:
                self.assertEqual(store.data["jobs"][0]["id"], "abc")


if __name__ == "__main__":
    unittest.main()
