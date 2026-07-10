from __future__ import annotations

import contextlib
import io
import unittest
from unittest import mock

from codex_wakectl import activity
from codex_wakectl import cli
from codex_wakectl import live_commands


class FakeInspectionAppServer:
    requests: list[tuple[str, dict | None]] = []
    turns_by_view: dict[str, list[dict]] = {}

    def __init__(self, endpoint: str, timeout: float) -> None:
        self.requests.clear()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def request(self, method: str, params=None):
        self.requests.append((method, params))
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
            return {"data": self.turns_by_view[params["itemsView"]]}
        raise AssertionError(f"unexpected method: {method}")


class ActivityTests(unittest.TestCase):
    def test_inspection_omits_command_output_and_keeps_recent_activity(self) -> None:
        detailed = {
            "id": "turn-2",
            "status": "inProgress",
            "itemsView": "full",
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
                    "status": "completed",
                    "durationMs": 1250,
                    "aggregatedOutput": "large private output",
                    "exitCode": 0,
                },
            ],
        }
        previous = {
            "id": "turn-1",
            "status": "completed",
            "itemsView": "summary",
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
        self.assertIn(
            'commandExecution:completed\t"cargo test"\tduration=1250ms\texit=0\tcwd="/repo"',
            rendered,
        )
        self.assertIn("latest\tinProgress\tturn-2", rendered)
        self.assertIn("view=full", rendered)
        self.assertIn("previous\tcompleted\tturn-1", rendered)
        self.assertIn("duration=9000ms", rendered)
        self.assertNotIn("large private output", rendered)

    def test_failed_turn_error_is_rendered(self) -> None:
        turn = activity.summarize_turn(
            {
                "id": "turn-failed",
                "status": "failed",
                "error": {"message": "model request failed"},
                "startedAt": 1,
                "completedAt": 2,
                "durationMs": 1000,
                "items": [],
            },
            12,
        )
        rendered = activity.format_inspection(
            {
                "thread": {"id": "thread", "loaded": True, "status": {"type": "idle"}},
                "goal": None,
                "goalError": None,
                "latestTurn": turn,
                "previousTurn": None,
            }
        )

        self.assertIn('latest:error\t{"message":"model request failed"}', rendered)

    def test_newer_summary_turn_wins_over_stale_detail(self) -> None:
        result = activity.build_inspection(
            {"id": "thread", "status": {"type": "active"}},
            loaded=True,
            goal=None,
            goal_error=None,
            detailed_turn={
                "id": "old",
                "status": "completed",
                "itemsView": "full",
                "items": [],
            },
            summary_turns=[
                {
                    "id": "new",
                    "status": "inProgress",
                    "itemsView": "summary",
                    "items": [],
                },
                {
                    "id": "old",
                    "status": "completed",
                    "itemsView": "summary",
                    "items": [],
                },
            ],
            item_limit=12,
        )

        self.assertEqual(result["latestTurn"]["id"], "new")
        self.assertEqual(result["latestTurn"]["itemsView"], "summary")
        self.assertEqual(result["previousTurn"]["id"], "old")

    def test_fresh_summary_replaces_stale_full_turn(self) -> None:
        result = activity.build_inspection(
            {"id": "thread", "status": {"type": "idle"}},
            loaded=True,
            goal=None,
            goal_error=None,
            detailed_turn={
                "id": "turn",
                "status": "inProgress",
                "itemsView": "full",
                "startedAt": 1,
                "completedAt": None,
                "durationMs": None,
                "items": [
                    {
                        "type": "commandExecution",
                        "id": "command",
                        "status": "inProgress",
                        "command": "true",
                    }
                ],
            },
            summary_turns=[
                {
                    "id": "turn",
                    "status": "completed",
                    "itemsView": "summary",
                    "startedAt": 1,
                    "completedAt": 3,
                    "durationMs": 2000,
                    "items": [
                        {
                            "type": "agentMessage",
                            "id": "answer",
                            "phase": "final_answer",
                            "text": "Done.",
                        }
                    ],
                }
            ],
            item_limit=12,
        )

        latest = result["latestTurn"]
        self.assertEqual(latest["status"], "completed")
        self.assertEqual(latest["completedAt"], 3)
        self.assertEqual(latest["durationMs"], 2000)
        self.assertEqual(latest["itemsView"], "summary")
        self.assertEqual([item["type"] for item in latest["items"]], ["agentMessage"])

    def test_unchanged_lifecycle_keeps_full_activity(self) -> None:
        detail = {
            "id": "turn",
            "status": "inProgress",
            "itemsView": "full",
            "startedAt": 1,
            "completedAt": None,
            "durationMs": None,
            "error": None,
            "items": [
                {
                    "type": "commandExecution",
                    "id": "command",
                    "status": "inProgress",
                    "command": "sleep 10",
                }
            ],
        }
        summary = {
            **detail,
            "itemsView": "summary",
            "items": [
                {
                    "type": "agentMessage",
                    "id": "update",
                    "phase": "commentary",
                    "text": "Still working.",
                }
            ],
        }
        result = activity.build_inspection(
            {"id": "thread", "status": {"type": "active"}},
            loaded=True,
            goal=None,
            goal_error=None,
            detailed_turn=detail,
            summary_turns=[summary],
            item_limit=12,
        )

        latest = result["latestTurn"]
        self.assertEqual(latest["itemsView"], "full")
        self.assertEqual(
            [item["type"] for item in latest["items"]],
            ["commandExecution", "agentMessage"],
        )

    def test_empty_fresh_summary_does_not_restore_old_detail(self) -> None:
        result = activity.build_inspection(
            {"id": "thread", "status": {"type": "idle"}},
            loaded=True,
            goal=None,
            goal_error=None,
            detailed_turn={
                "id": "removed",
                "status": "completed",
                "itemsView": "full",
                "items": [],
            },
            summary_turns=[],
            item_limit=12,
        )

        self.assertIsNone(result["latestTurn"])

    def test_zero_duration_is_reported_as_sub_millisecond(self) -> None:
        self.assertIn(
            "duration=<1ms",
            activity.item_line(
                "",
                {
                    "type": "commandExecution",
                    "status": "completed",
                    "durationMs": 0,
                    "command": "true",
                },
            ),
        )
        self.assertEqual(
            activity.item_line("", {"type": "contextCompaction"}),
            "contextCompaction",
        )
        self.assertEqual(
            activity.item_line("", {"type": "sleep", "durationMs": 0}),
            "sleep\trequested=<1ms",
        )

    def test_failed_mcp_and_collaboration_details_are_rendered(self) -> None:
        mcp = activity.summarize_item(
            {
                "type": "mcpToolCall",
                "status": "failed",
                "server": "git",
                "tool": "read",
                "error": {"message": "not found"},
            }
        )
        collab = activity.summarize_item(
            {
                "type": "collabAgentToolCall",
                "tool": "wait",
                "receiverThreadIds": ["worker"],
                "agentsStates": {
                    "worker": {"status": "completed", "message": "large result"}
                },
            }
        )

        mcp_line = activity.item_line("", mcp)
        self.assertTrue(mcp_line.startswith('mcpToolCall:failed\t"git:read"'))
        self.assertIn('error={"message":"not found"}', mcp_line)
        collab_line = activity.item_line("", collab)
        self.assertIn(
            '"states":{"worker":"completed"}',
            collab_line,
        )
        self.assertNotIn("large result", collab_line)
        collab_json = activity.quoted(collab)
        self.assertIn(
            '"agentsStates":{"worker":{"status":"completed"}}',
            collab_json,
        )
        self.assertNotIn("large result", collab_json)

    def test_inspect_brief_avoids_full_turn_load(self) -> None:
        FakeInspectionAppServer.turns_by_view = {
            "summary": [
                {
                    "id": "turn-1",
                    "status": "completed",
                    "itemsView": "summary",
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
            ]
        }

        args = cli.build_parser().parse_args(
            ["inspect", "thread", "--brief", "--no-previous", "--json"]
        )
        stdout = io.StringIO()
        with (
            mock.patch.object(live_commands, "AppServer", FakeInspectionAppServer),
            contextlib.redirect_stdout(stdout),
        ):
            rc = cli.asyncio.run(args.func(args))

        self.assertEqual(rc, 0)
        self.assertIn('"latestTurn"', stdout.getvalue())
        self.assertIn('"text": "Done."', stdout.getvalue())
        turn_requests = [
            params
            for method, params in FakeInspectionAppServer.requests
            if method == "thread/turns/list"
        ]
        self.assertEqual(len(turn_requests), 1)
        self.assertEqual(turn_requests[0]["limit"], 1)
        self.assertEqual(turn_requests[0]["itemsView"], "summary")
        self.assertEqual(FakeInspectionAppServer.requests[-1][0], "thread/loaded/list")

    def test_inspect_full_prefers_changed_final_summary(self) -> None:
        FakeInspectionAppServer.turns_by_view = {
            "full": [
                {
                    "id": "turn",
                    "status": "inProgress",
                    "itemsView": "full",
                    "completedAt": None,
                    "items": [
                        {
                            "type": "commandExecution",
                            "id": "command",
                            "status": "completed",
                            "command": "true",
                        }
                    ],
                }
            ],
            "summary": [
                {
                    "id": "turn",
                    "status": "completed",
                    "itemsView": "summary",
                    "completedAt": 3,
                    "durationMs": 2000,
                    "items": [
                        {
                            "type": "agentMessage",
                            "id": "answer",
                            "text": "Done.",
                        }
                    ],
                }
            ],
        }
        args = cli.build_parser().parse_args(
            ["inspect", "thread", "--no-previous", "--json"]
        )
        stdout = io.StringIO()
        with (
            mock.patch.object(live_commands, "AppServer", FakeInspectionAppServer),
            contextlib.redirect_stdout(stdout),
        ):
            rc = cli.asyncio.run(args.func(args))

        self.assertEqual(rc, 0)
        output = stdout.getvalue()
        self.assertIn('"id": "turn"', output)
        self.assertIn('"status": "completed"', output)
        self.assertIn('"itemsView": "summary"', output)
        self.assertIn('"text": "Done."', output)
        turn_views = [
            params["itemsView"]
            for method, params in FakeInspectionAppServer.requests
            if method == "thread/turns/list"
        ]
        self.assertEqual(turn_views, ["full", "summary"])


if __name__ == "__main__":
    unittest.main()
