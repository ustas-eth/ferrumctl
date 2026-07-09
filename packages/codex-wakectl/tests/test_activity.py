from __future__ import annotations

import contextlib
import io
import unittest
from unittest import mock

from codex_wakectl import activity
from codex_wakectl import cli
from codex_wakectl import live_commands


class ActivityTests(unittest.TestCase):
    def test_inspection_omits_command_output_and_keeps_recent_activity(self) -> None:
        detailed = {
            "id": "turn-2",
            "status": "inProgress",
            "startedAt": 20,
            "completedAt": None,
            "durationMs": None,
            "items": [
                {
                    "type": "agentMessage",
                    "id": "a1",
                    "phase": "commentary",
                    "text": "Checking the implementation.",
                },
                {
                    "type": "commandExecution",
                    "id": "c1",
                    "command": "cargo test",
                    "cwd": "/repo",
                    "status": "inProgress",
                    "aggregatedOutput": "large private output",
                    "exitCode": None,
                },
            ],
        }
        previous = {
            "id": "turn-1",
            "status": "completed",
            "startedAt": 1,
            "completedAt": 10,
            "durationMs": 9000,
            "items": [
                {
                    "type": "agentMessage",
                    "id": "a0",
                    "phase": "final_answer",
                    "text": "Previous result.",
                }
            ],
        }

        result = activity.build_inspection(
            {
                "id": "thread",
                "status": {"type": "active", "activeFlags": []},
                "cwd": "/repo",
            },
            loaded=True,
            goal={"status": "active", "objective": "Review", "tokensUsed": 12},
            goal_error=None,
            detailed_turn=detailed,
            summary_turns=[detailed, previous],
            item_limit=12,
        )

        command = result["latestTurn"]["items"][1]
        self.assertEqual(command["command"], "cargo test")
        self.assertNotIn("aggregatedOutput", command)
        self.assertEqual(result["previousTurn"]["items"][0]["text"], "Previous result.")
        self.assertIn("startedAgoSeconds", result["latestTurn"])
        self.assertIn("completedAgoSeconds", result["previousTurn"])
        rendered = activity.format_inspection(result)
        self.assertIn("thread\tloaded\tactive\tthread", rendered)
        self.assertIn('meta\tcwd="/repo"', rendered)
        self.assertIn("commandExecution:inProgress", rendered)
        self.assertNotIn("large private output", rendered)

    def test_inspect_command_reads_paged_turns(self) -> None:
        class FakeAppServer:
            def __init__(self, endpoint: str, timeout: float) -> None:
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args: object) -> None:
                return None

            async def request(self, method: str, params=None):
                if method == "thread/loaded/list":
                    return {"data": ["thread"], "nextCursor": None}
                if method == "thread/read":
                    return {
                        "thread": {
                            "id": "thread",
                            "status": {"type": "idle"},
                            "cwd": "/repo",
                        }
                    }
                if method == "thread/goal/get":
                    return {"goal": None}
                if method == "thread/turns/list":
                    turn = {
                        "id": "turn-1",
                        "status": "completed",
                        "startedAt": 1,
                        "completedAt": 2,
                        "durationMs": 1000,
                        "items": [
                            {
                                "type": "agentMessage",
                                "id": "a1",
                                "phase": "final_answer",
                                "text": "Done.",
                            }
                        ],
                    }
                    return {"data": [turn]}
                raise AssertionError(f"unexpected method: {method}")

        args = cli.build_parser().parse_args(["inspect", "thread", "--json"])
        stdout = io.StringIO()
        with (
            mock.patch.object(live_commands, "AppServer", FakeAppServer),
            contextlib.redirect_stdout(stdout),
        ):
            rc = cli.asyncio.run(args.func(args))

        self.assertEqual(rc, 0)
        self.assertIn('"latestTurn"', stdout.getvalue())
        self.assertIn('"text": "Done."', stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
