import unittest

from codex_threadctl import formatting


class FormattingTests(unittest.TestCase):
    def test_inspection_labels_independent_state_surfaces(self):
        inspection = {
            "thread": {
                "id": "thread",
                "loaded": True,
                "status": {"type": "active", "activeFlags": ["waiting"]},
                "cwd": "/work",
            },
            "context": {
                "usedTokens": 50_000,
                "windowTokens": 200_000,
                "percentLeft": 80,
                "observedAt": 1,
                "observedAgoSeconds": 4,
            },
            "compaction": {"windowNumber": 2, "lastAt": 1, "lastAgoSeconds": 5},
            "goal": {
                "status": "active",
                "objective": "review",
                "tokensUsed": 100,
                "tokenBudget": 1000,
                "timeUsedSeconds": 3,
            },
            "goalError": None,
            "latestTurn": {
                "id": "turn",
                "status": "inProgress",
                "itemsView": "full",
                "startedAt": 1,
                "completedAt": None,
                "startedAgoSeconds": 5,
                "completedAgoSeconds": None,
                "durationMs": None,
                "error": None,
                "items": [
                    {
                        "type": "commandExecution",
                        "status": "completed",
                        "command": "make test",
                        "cwd": "/work",
                        "exitCode": 0,
                        "durationMs": 0,
                    }
                ],
            },
            "previousTurn": None,
        }
        output = formatting.format_inspection(inspection)
        self.assertIn("thread\tloaded\tactive\tthread", output)
        self.assertIn("context\tused=50000\twindow=200000\tleft=80%", output)
        self.assertIn("goal\tactive\ttokens=100\tbudget=1000\ttime=3s", output)
        self.assertIn('commandExecution:completed\t"make test"\tduration=<1ms\texit=0', output)

    def test_message_preview_is_single_line_and_bounded(self):
        preview = formatting.message_preview("first\n" + "x" * 200)
        self.assertNotIn("\n", preview)
        self.assertEqual(len(preview), 160)
        self.assertTrue(preview.endswith("..."))
