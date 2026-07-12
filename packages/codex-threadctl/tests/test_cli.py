import io
import json
import unittest
from contextlib import redirect_stdout
from unittest import mock

from codex_threadctl import commands, parser


class FakeContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return None


class ParserTests(unittest.TestCase):
    def test_version(self):
        with redirect_stdout(io.StringIO()) as output:
            with self.assertRaisesRegex(SystemExit, "0"):
                parser.build_parser().parse_args(["--version"])
        self.assertEqual(output.getvalue(), "codex-threadctl 0.3.0\n")

    def test_parses_all_commands(self):
        cases = [
            ["loaded"],
            ["list", "--parent", "thread", "--limit", "0", "--sort", "created"],
            ["search", "decision text", "--limit", "0", "--sort", "updated"],
            ["status", "thread"],
            ["inspect", "thread", "--brief", "--items", "0"],
            ["messages", "thread", "--limit", "0"],
            ["message", "thread", "turn", "item"],
            ["start", "thread", "message"],
            ["steer", "thread", "turn", "message"],
            ["interrupt", "thread", "turn", "--wait"],
            ["terminals", "thread", "--limit", "0"],
            ["terminate-terminal", "thread", "42", "--item", "item"],
            ["resume", "thread", "--continue-goal"],
        ]
        for argv in cases:
            with self.subTest(argv=argv):
                self.assertTrue(callable(parser.build_parser().parse_args(argv).func))

    def test_list_relationship_filters_are_mutually_exclusive(self):
        with self.assertRaises(SystemExit):
            parser.build_parser().parse_args(
                ["list", "--parent", "parent", "--ancestor", "ancestor"]
            )

    def test_search_rejects_empty_text(self):
        with self.assertRaises(SystemExit):
            parser.build_parser().parse_args(["search", "  "])

    def test_destructive_controls_require_explicit_identity_and_intent(self):
        with self.assertRaises(SystemExit):
            parser.build_parser().parse_args(
                ["terminate-terminal", "thread", "42"]
            )
        with self.assertRaises(SystemExit):
            parser.build_parser().parse_args(["resume", "thread"])

    def test_global_options_work_after_subcommand(self):
        args = parser.build_parser().parse_args(
            ["inspect", "thread", "--endpoint", "unix:///tmp/socket", "--json"]
        )
        self.assertEqual(args.endpoint, "unix:///tmp/socket")
        self.assertTrue(args.json)

    def test_timeout_rejects_non_finite_values(self):
        for value in ("nan", "inf", "-inf"):
            with self.subTest(value=value):
                with self.assertRaises(SystemExit):
                    parser.build_parser().parse_args(["--timeout", value, "loaded"])


class CommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_loaded_prints_nothing_for_empty_result(self):
        args = parser.build_parser().parse_args(["loaded"])
        with (
            mock.patch.object(commands, "AppServer", return_value=FakeContext()),
            mock.patch.object(commands, "list_loaded", mock.AsyncMock(return_value=[])),
            redirect_stdout(io.StringIO()) as output,
        ):
            result = await commands.cmd_loaded(args)
        self.assertEqual(result, 0)
        self.assertEqual(output.getvalue(), "")

    async def test_list_passes_filters_and_prints_id_first(self):
        args = parser.build_parser().parse_args(
            ["list", "--parent", "parent", "--limit", "2", "--sort", "created"]
        )
        threads = [
            {
                "id": "child",
                "status": {"type": "notLoaded"},
                "createdAt": 1,
                "updatedAt": 2,
                "recencyAt": 2,
                "agentNickname": "Ada",
                "agentRole": "explorer",
                "parentThreadId": "parent",
                "cwd": "/work",
                "preview": "Review the code",
            }
        ]
        with (
            mock.patch.object(commands, "AppServer", return_value=FakeContext()),
            mock.patch.object(
                commands,
                "list_threads",
                mock.AsyncMock(return_value=threads),
            ) as list_threads,
            redirect_stdout(io.StringIO()) as output,
        ):
            result = await commands.cmd_list(args)
        self.assertEqual(result, 0)
        list_threads.assert_awaited_once_with(
            mock.ANY,
            parent_thread_id="parent",
            ancestor_thread_id=None,
            limit=2,
            sort_key="created_at",
        )
        self.assertTrue(output.getvalue().startswith("child\tserver=notLoaded\t"))
        self.assertIn('nickname="Ada"', output.getvalue())

    async def test_list_json_has_stable_selected_fields(self):
        args = parser.build_parser().parse_args(["list", "--json"])
        thread = {
            "id": "thread",
            "status": {"type": "idle"},
            "createdAt": 1,
            "extra": "not exposed",
        }
        with (
            mock.patch.object(commands, "AppServer", return_value=FakeContext()),
            mock.patch.object(
                commands,
                "list_threads",
                mock.AsyncMock(return_value=[thread]),
            ) as list_threads,
            redirect_stdout(io.StringIO()) as output,
        ):
            result = await commands.cmd_list(args)
        self.assertEqual(result, 0)
        list_threads.assert_awaited_once_with(
            mock.ANY,
            parent_thread_id=None,
            ancestor_thread_id=None,
            limit=20,
            sort_key="recency_at",
        )
        result = json.loads(output.getvalue())
        self.assertEqual(result["threads"][0]["id"], "thread")
        self.assertNotIn("extra", result["threads"][0])

    async def test_search_prints_match_snippet_and_stable_json(self):
        args = parser.build_parser().parse_args(
            ["search", "decision", "--limit", "2", "--sort", "updated", "--json"]
        )
        matches = [
            {
                "thread": {
                    "id": "thread",
                    "status": {"type": "notLoaded"},
                    "updatedAt": 2,
                    "preview": "unrelated preview",
                    "extra": "not exposed",
                },
                "snippet": "the matching decision",
            }
        ]
        with (
            mock.patch.object(commands, "AppServer", return_value=FakeContext()),
            mock.patch.object(
                commands,
                "search_threads",
                mock.AsyncMock(return_value=matches),
            ) as search_threads,
            redirect_stdout(io.StringIO()) as output,
        ):
            result = await commands.cmd_search(args)
        self.assertEqual(result, 0)
        search_threads.assert_awaited_once_with(
            mock.ANY,
            "decision",
            limit=2,
            sort_key="updated_at",
        )
        record = json.loads(output.getvalue())["threads"][0]
        self.assertEqual(record["snippet"], "the matching decision")
        self.assertNotIn("preview", record)
        self.assertNotIn("extra", record)

    async def test_terminals_prints_process_id_first(self):
        args = parser.build_parser().parse_args(["terminals", "thread"])
        terminals = [
            {
                "processId": "42",
                "itemId": "item",
                "osPid": 123,
                "cpuPercent": 2.5,
                "rssKb": 4096,
                "cwd": "/work",
                "command": "printf 'a  b'\nsleep 10 " + "x" * 240,
            }
        ]
        with (
            mock.patch.object(commands, "AppServer", return_value=FakeContext()),
            mock.patch.object(
                commands,
                "list_background_terminals",
                mock.AsyncMock(return_value=terminals),
            ) as list_terminals,
            redirect_stdout(io.StringIO()) as output,
        ):
            result = await commands.cmd_terminals(args)
        self.assertEqual(result, 0)
        list_terminals.assert_awaited_once_with(mock.ANY, "thread", limit=20)
        self.assertTrue(output.getvalue().startswith("42\titem=item\tpid=123\t"))
        self.assertIn(
            'command="printf \'a  b\'\\nsleep 10 ' + "x" * 240 + '"',
            output.getvalue(),
        )

    async def test_terminate_terminal_requires_native_confirmation(self):
        args = parser.build_parser().parse_args(
            ["terminate-terminal", "thread", "42", "--item", "item"]
        )
        with (
            mock.patch.object(commands, "AppServer", return_value=FakeContext()),
            mock.patch.object(
                commands,
                "terminate_background_terminal",
                mock.AsyncMock(return_value=False),
            ) as terminate_terminal,
        ):
            with self.assertRaisesRegex(commands.ThreadctlError, "was not terminated"):
                await commands.cmd_terminate_terminal(args)
        terminate_terminal.assert_awaited_once_with(
            mock.ANY,
            "thread",
            "42",
            "item",
        )

    async def test_terminate_terminal_reports_confirmed_identity(self):
        args = parser.build_parser().parse_args(
            [
                "terminate-terminal",
                "thread",
                "42",
                "--item",
                "item",
                "--json",
            ]
        )
        with (
            mock.patch.object(commands, "AppServer", return_value=FakeContext()),
            mock.patch.object(
                commands,
                "terminate_background_terminal",
                mock.AsyncMock(return_value=True),
            ),
            redirect_stdout(io.StringIO()) as output,
        ):
            result = await commands.cmd_terminate_terminal(args)
        self.assertEqual(result, 0)
        self.assertEqual(
            json.loads(output.getvalue()),
            {
                "threadId": "thread",
                "processId": "42",
                "itemId": "item",
                "terminated": True,
            },
        )

    async def test_resume_passes_goal_continuation_intent(self):
        args = parser.build_parser().parse_args(
            ["resume", "thread", "--continue-goal", "--json"]
        )
        thread = {"id": "thread", "status": {"type": "idle"}}
        with (
            mock.patch.object(commands, "AppServer", return_value=FakeContext()),
            mock.patch.object(
                commands,
                "resume_thread",
                mock.AsyncMock(return_value=thread),
            ) as resume_thread,
            redirect_stdout(io.StringIO()) as output,
        ):
            result = await commands.cmd_resume(args)
        self.assertEqual(result, 0)
        resume_thread.assert_awaited_once_with(
            mock.ANY,
            "thread",
            continue_goal=True,
        )
        self.assertTrue(json.loads(output.getvalue())["goalContinuationAllowed"])

    async def test_message_prints_exact_multiline_text(self):
        args = parser.build_parser().parse_args(["message", "thread", "turn", "item"])
        with (
            mock.patch.object(commands, "AppServer", return_value=FakeContext()),
            mock.patch.object(
                commands,
                "find_message",
                mock.AsyncMock(return_value={"text": "first\nsecond"}),
            ),
            redirect_stdout(io.StringIO()) as output,
        ):
            result = await commands.cmd_message(args)
        self.assertEqual(result, 0)
        self.assertEqual(output.getvalue(), "first\nsecond\n")

    async def test_messages_plain_output_contains_composite_locator(self):
        args = parser.build_parser().parse_args(["messages", "thread"])
        messages = [
            {
                "role": "agent",
                "turnId": "turn",
                "itemId": "item-2",
                "phase": "final_answer",
                "text": "done",
                "startedAt": 0,
                "completedAt": 1,
            }
        ]
        with (
            mock.patch.object(commands, "AppServer", return_value=FakeContext()),
            mock.patch.object(commands, "recent_messages", mock.AsyncMock(return_value=messages)),
            redirect_stdout(io.StringIO()) as output,
        ):
            result = await commands.cmd_messages(args)
        self.assertEqual(result, 0)
        self.assertIn("turn\titem-2\tfinal_answer", output.getvalue())
