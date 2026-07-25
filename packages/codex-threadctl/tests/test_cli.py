import io
import json
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

from codex_threadctl import commands, parser


class FakeContext:
    def __init__(self, value=None):
        self.value = object() if value is None else value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, tb):
        return None


class ParserTests(unittest.TestCase):
    def test_version(self):
        with redirect_stdout(io.StringIO()) as output:
            with self.assertRaisesRegex(SystemExit, "0"):
                parser.build_parser().parse_args(["--version"])
        self.assertEqual(output.getvalue(), "codex-threadctl 0.5.2\n")

    def test_default_timeout_allows_for_history_reconstruction(self):
        self.assertEqual(parser.build_parser().parse_args(["loaded"]).timeout, 30.0)

    def test_parses_all_commands(self):
        cases = [
            ["loaded"],
            ["list", "--parent", "thread", "--limit", "0", "--sort", "created"],
            ["search", "decision text", "--limit", "0", "--sort", "updated"],
            ["status", "thread"],
            ["inspect", "thread", "--brief", "--items", "0"],
            [
                "messages",
                "thread",
                "--turn",
                "turn",
                "--after",
                "turn",
                "item-1",
                "--before",
                "turn",
                "item-3",
                "--limit",
                "0",
            ],
            [
                "items",
                "thread",
                "--type",
                "userMessage",
                "--type",
                "agentMessage",
                "--limit",
                "0",
            ],
            ["message", "thread", "turn", "item"],
            ["start", "thread", "message"],
            ["notify", "thread", "--from", "author", "message"],
            ["wake", "thread"],
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

    async def test_notify_uses_current_thread_identity_and_prints_acceptance(self):
        args = parser.build_parser().parse_args(["notify", "target", "notice"])
        with (
            mock.patch.dict("os.environ", {"CODEX_THREAD_ID": "author"}),
            mock.patch.object(commands, "AppServer", return_value=FakeContext()),
            mock.patch.object(
                commands,
                "notify_thread",
                mock.AsyncMock(
                    return_value={
                        "threadId": "target",
                        "author": "author",
                        "outcome": "accepted",
                    }
                ),
            ) as notify_thread,
            redirect_stdout(io.StringIO()) as output,
        ):
            result = await commands.cmd_notify(args)

        self.assertEqual(result, 0)
        notify_thread.assert_awaited_once_with(
            mock.ANY,
            "target",
            "author",
            "notice",
        )
        self.assertEqual(output.getvalue(), "accepted\ttarget\n")

    async def test_notify_requires_an_author_identity(self):
        args = parser.build_parser().parse_args(["notify", "target", "notice"])
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(commands.ThreadctlError, "--from"):
                await commands.cmd_notify(args)

    async def test_wake_reports_outcome_and_exit_status(self):
        cases = [
            ("confirmedStarted", 0),
            ("notSubmittedActive", 0),
            ("notLoaded", 1),
            ("rejected", 1),
            ("uncertain", 1),
        ]
        for outcome, expected_status in cases:
            with self.subTest(outcome=outcome):
                args = parser.build_parser().parse_args(["wake", "thread", "--json"])
                result = {"threadId": "thread", "outcome": outcome}
                with (
                    mock.patch.object(
                        commands,
                        "AppServer",
                        return_value=FakeContext(),
                    ),
                    mock.patch.object(
                        commands,
                        "wake_thread",
                        mock.AsyncMock(return_value=result),
                    ),
                    redirect_stdout(io.StringIO()) as output,
                ):
                    status = await commands.cmd_wake(args)
                self.assertEqual(status, expected_status)
                self.assertEqual(json.loads(output.getvalue()), result)

    async def test_inspect_reads_turn_history_once(self):
        args = parser.build_parser().parse_args(["inspect", "thread", "--json"])
        page = {
            "data": [
                {
                    "id": "latest",
                    "status": "inProgress",
                    "itemsView": "full",
                    "items": [],
                },
                {
                    "id": "previous",
                    "status": "completed",
                    "itemsView": "full",
                    "items": [],
                },
            ]
        }
        list_turn_page = mock.AsyncMock(return_value=page)
        app = SimpleNamespace(endpoint="unix://")
        with (
            mock.patch.object(commands, "AppServer", return_value=FakeContext(app)),
            mock.patch.object(commands, "list_turn_page", list_turn_page),
            mock.patch.object(commands, "get_goal", mock.AsyncMock(return_value=None)),
            mock.patch.object(
                commands,
                "read_thread",
                mock.AsyncMock(
                    return_value={
                        "id": "thread",
                        "status": {"type": "active"},
                        "path": None,
                    }
                ),
            ),
            mock.patch.object(
                commands,
                "list_loaded",
                mock.AsyncMock(return_value=["thread"]),
            ),
            mock.patch.object(
                commands,
                "read_context_state",
                return_value=(None, None),
            ),
            redirect_stdout(io.StringIO()) as output,
        ):
            result = await commands.cmd_inspect(args)

        self.assertEqual(result, 0)
        list_turn_page.assert_awaited_once_with(
            app,
            "thread",
            limit=2,
            items_view="full",
        )
        inspection = json.loads(output.getvalue())
        self.assertEqual(inspection["latestTurn"]["id"], "latest")
        self.assertEqual(inspection["previousTurn"]["id"], "previous")

    async def test_inspect_falls_back_to_unattributed_native_items(self):
        args = parser.build_parser().parse_args(["inspect", "thread", "--json"])
        unsupported = commands.AppServerResponseError(
            {"code": -32601, "message": "paginated_threads is not supported yet"}
        )
        app = SimpleNamespace(endpoint="unix://")
        recent = [{"id": "item", "type": "agentMessage", "text": "working"}]
        with (
            mock.patch.object(commands, "AppServer", return_value=FakeContext(app)),
            mock.patch.object(
                commands,
                "list_turn_page",
                mock.AsyncMock(side_effect=unsupported),
            ),
            mock.patch.object(
                commands,
                "native_inspection_history",
                mock.AsyncMock(return_value=([], recent)),
            ),
            mock.patch.object(commands, "get_goal", mock.AsyncMock(return_value=None)),
            mock.patch.object(
                commands,
                "read_thread",
                mock.AsyncMock(
                    return_value={
                        "id": "thread",
                        "status": {"type": "idle"},
                        "path": None,
                    }
                ),
            ),
            mock.patch.object(
                commands,
                "list_loaded",
                mock.AsyncMock(return_value=["thread"]),
            ),
            mock.patch.object(
                commands,
                "read_context_state",
                return_value=(None, None),
            ),
            redirect_stdout(io.StringIO()) as output,
        ):
            result = await commands.cmd_inspect(args)

        self.assertEqual(result, 0)
        inspection = json.loads(output.getvalue())
        self.assertEqual(inspection["historyBackend"], "thread/items/list")
        self.assertIn("does not expose turn ids", inspection["historyError"])
        self.assertEqual(inspection["recentItems"][0]["text"], "working")

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
            mock.patch.object(
                commands,
                "recent_messages",
                mock.AsyncMock(return_value=(messages, "thread/turns/list")),
            ),
            redirect_stdout(io.StringIO()) as output,
        ):
            result = await commands.cmd_messages(args)
        self.assertEqual(result, 0)
        self.assertIn("turn\titem-2\tfinal_answer", output.getvalue())

    async def test_messages_passes_range_and_reports_materialized_backend(self):
        args = parser.build_parser().parse_args(
            [
                "messages",
                "thread",
                "--turn",
                "turn",
                "--after",
                "turn",
                "first",
                "--before",
                "turn",
                "last",
                "--limit",
                "0",
                "--json",
            ]
        )
        recent = mock.AsyncMock(return_value=([], "thread/items/list"))
        with (
            mock.patch.object(commands, "AppServer", return_value=FakeContext()),
            mock.patch.object(commands, "recent_messages", recent),
            redirect_stdout(io.StringIO()) as output,
        ):
            result = await commands.cmd_messages(args)

        self.assertEqual(result, 0)
        recent.assert_awaited_once_with(
            mock.ANY,
            "thread",
            turn_id="turn",
            after=("turn", "first"),
            before=("turn", "last"),
            limit=0,
        )
        self.assertEqual(
            json.loads(output.getvalue()),
            {
                "threadId": "thread",
                "view": "materialized",
                "backend": "thread/items/list",
                "messages": [],
            },
        )

    async def test_items_outputs_compact_records(self):
        args = parser.build_parser().parse_args(
            ["items", "thread", "--type", "commandExecution", "--json"]
        )
        entry = SimpleNamespace(
            turn={"id": "turn", "status": "completed"},
            item={
                "id": "item",
                "type": "commandExecution",
                "status": "completed",
                "command": "true",
                "aggregatedOutput": "omitted",
            },
        )
        selection = SimpleNamespace(
            entries=[entry],
            backend="thread/turns/list",
        )
        selected = mock.AsyncMock(return_value=selection)
        with (
            mock.patch.object(commands, "AppServer", return_value=FakeContext()),
            mock.patch.object(commands, "select_materialized_items", selected),
            redirect_stdout(io.StringIO()) as output,
        ):
            result = await commands.cmd_items(args)

        self.assertEqual(result, 0)
        selected.assert_awaited_once_with(
            mock.ANY,
            "thread",
            turn_id=None,
            after=None,
            before=None,
            types={"commandExecution"},
            limit=20,
        )
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["items"][0]["itemId"], "item")
        self.assertNotIn("aggregatedOutput", payload["items"][0])
