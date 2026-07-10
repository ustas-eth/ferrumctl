import unittest

from codex_threadctl import items
from codex_threadctl.errors import ThreadctlError


class ItemTests(unittest.TestCase):
    def test_summarizes_command_without_output(self):
        result = items.summarize_item(
            {
                "id": "exec-1",
                "type": "commandExecution",
                "status": "completed",
                "command": "make test",
                "cwd": "/work",
                "exitCode": 0,
                "aggregatedOutput": "large output",
            }
        )
        self.assertEqual(
            result,
            {
                "id": "exec-1",
                "type": "commandExecution",
                "status": "completed",
                "command": "make test",
                "cwd": "/work",
                "exitCode": 0,
            },
        )

    def test_summarizes_tool_and_file_activity(self):
        file_change = items.summarize_item(
            {
                "type": "fileChange",
                "changes": [
                    {"path": "a.py", "kind": "update", "diff": "omitted"},
                    {"path": "b.py", "kind": "add"},
                ],
            }
        )
        mcp = items.summarize_item(
            {"type": "mcpToolCall", "server": "git", "tool": "status", "error": None}
        )
        dynamic = items.summarize_item(
            {"type": "dynamicToolCall", "namespace": "x", "tool": "run", "success": True}
        )
        self.assertEqual(file_change["changes"][0], {"path": "a.py", "kind": "update"})
        self.assertEqual(mcp["tool"], "status")
        self.assertTrue(dynamic["success"])

    def test_bounds_collaboration_state(self):
        result = items.summarize_item(
            {
                "type": "collabAgentToolCall",
                "tool": "wait",
                "agentsStates": {
                    "a": {"status": "running", "large": "omitted"},
                    "b": "completed",
                },
            }
        )
        self.assertEqual(
            result["agentsStates"],
            {"a": {"status": "running"}, "b": {"status": "completed"}},
        )

    def test_message_record_preserves_multiline_text_and_locator(self):
        result = items.message_record(
            {"id": "turn", "status": "completed", "startedAt": 1, "completedAt": 2},
            {
                "id": "item",
                "type": "userMessage",
                "clientId": "client",
                "content": [
                    {"type": "text", "text": "first"},
                    {"type": "image", "url": "ignored"},
                    {"type": "text", "text": "second"},
                ],
            },
        )
        self.assertEqual(result["text"], "first\nsecond")
        self.assertEqual((result["turnId"], result["itemId"]), ("turn", "item"))
        self.assertEqual(result["clientId"], "client")

    def test_rejects_non_message_text(self):
        with self.assertRaisesRegex(ThreadctlError, "not a conversation message"):
            items.message_text({"type": "commandExecution"})
