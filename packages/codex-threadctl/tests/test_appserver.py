import contextlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from codex_threadctl import appserver
from codex_threadctl.errors import (
    AppServerResponseError,
    DeliveryUncertain,
    DirectInputUnsupported,
    ThreadNotLoaded,
    ThreadStateError,
    ThreadctlError,
)


class FakeApp:
    def __init__(
        self,
        *,
        loaded=True,
        status="idle",
        actual_turn_id="submission",
        turn_status="inProgress",
    ):
        self.loaded = loaded
        self.status = status
        self.actual_turn_id = actual_turn_id
        self.turn_status = turn_status
        self.client_message_id = None
        self.timeout = 1
        self.calls = []
        self.turn_notifications = []

    async def request(self, method, params=None):
        self.calls.append((method, params))
        if method == "thread/loaded/list":
            return {"data": ["thread"] if self.loaded else [], "nextCursor": None}
        if method == "thread/read":
            return {"thread": {"id": "thread", "status": {"type": self.status}}}
        if method == "thread/turns/list":
            item = (
                {
                    "type": "userMessage",
                    "id": "item",
                    "clientId": self.client_message_id,
                    "content": [{"type": "text", "text": "message"}],
                }
                if self.client_message_id is not None
                else None
            )
            return {
                "data": [
                    {
                        "id": self.actual_turn_id,
                        "status": self.turn_status,
                        "items": [item] if item else [],
                    }
                ],
                "nextCursor": None,
            }
        if method == "thread/items/list":
            item = (
                {
                    "type": "userMessage",
                    "id": "item",
                    "clientId": self.client_message_id,
                    "content": [{"type": "text", "text": "message"}],
                }
                if self.client_message_id is not None
                else None
            )
            return {
                "data": (
                    [{"turnId": self.actual_turn_id, "item": item}]
                    if item is not None
                    else []
                ),
                "nextCursor": None,
            }
        if method == "turn/start":
            self.client_message_id = params.get("clientUserMessageId")
            return {"turn": {"id": "submission", "status": "inProgress"}}
        if method == "turn/steer":
            return {"turnId": params["expectedTurnId"]}
        if method == "turn/interrupt":
            self.turn_status = "interrupted"
            return {}
        if method == "thread/resume":
            return {"thread": {"id": params["threadId"], "status": {"type": "idle"}}}
        raise AssertionError(method)


class AppServerOperationTests(unittest.IsolatedAsyncioTestCase):
    async def test_v2_direct_input_rejections_name_parent_ownership(self):
        class ParentOwnedApp(FakeApp):
            async def request(self, method, params=None):
                if method in {"turn/start", "turn/steer"}:
                    raise AppServerResponseError(
                        {
                            "message": (
                                "direct app-server input is not allowed for "
                                "multi-agent v2 sub-agents"
                            )
                        }
                    )
                return await super().request(method, params)

        with self.assertRaisesRegex(DirectInputUnsupported, "native parent"):
            await appserver.start_turn(ParentOwnedApp(), "thread", "work")

        wake = await appserver.wake_thread(ParentOwnedApp(), "thread")
        self.assertEqual(wake["outcome"], "rejected")
        self.assertIn("native parent", wake["reason"])

        with self.assertRaisesRegex(DirectInputUnsupported, "native parent"):
            await appserver.steer_turn(
                ParentOwnedApp(status="active"),
                "thread",
                "submission",
                "change",
            )

    async def test_default_endpoint_uses_codex_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            with (
                contextlib.chdir(tmp),
                mock.patch.dict(os.environ, {"CODEX_HOME": "relative-home"}),
            ):
                result = appserver.resolve_unix_endpoint("unix://")
        expected = Path(tmp) / "relative-home/app-server-control/app-server-control.sock"
        self.assertEqual(result, str(expected))

    async def test_item_page_passes_native_pagination_fields(self):
        class ItemApp:
            def __init__(self):
                self.call = None

            async def request(self, method, params=None):
                self.call = (method, params)
                return {
                    "data": [{"id": "item", "type": "contextCompaction"}],
                    "nextCursor": None,
                }

        app = ItemApp()
        result = await appserver.list_item_page(
            app,
            "thread",
            turn_id="turn",
            cursor="cursor",
            limit=7,
            sort_direction="desc",
        )
        self.assertEqual(result["data"][0]["id"], "item")
        self.assertEqual(
            app.call,
            (
                "thread/items/list",
                {
                    "threadId": "thread",
                    "turnId": "turn",
                    "cursor": "cursor",
                    "limit": 7,
                    "sortDirection": "desc",
                },
            ),
        )

    async def test_item_page_accepts_turn_wrapped_items(self):
        class ItemApp:
            async def request(self, method, params=None):
                return {
                    "data": [
                        {
                            "turnId": "turn",
                            "item": {"id": "item", "type": "contextCompaction"},
                        }
                    ],
                    "nextCursor": None,
                }

        result = await appserver.list_item_page(ItemApp(), "thread", turn_id="turn")
        self.assertEqual(result["data"][0]["turnId"], "turn")

    async def test_history_pages_reject_malformed_records(self):
        class InvalidApp:
            async def request(self, method, params=None):
                if method == "thread/items/list":
                    return {"data": [{"id": "missing-type"}]}
                return {"data": [{"status": "completed"}]}

        with self.assertRaisesRegex(ThreadctlError, "invalid item data"):
            await appserver.list_item_page(InvalidApp(), "thread")
        with self.assertRaisesRegex(ThreadctlError, "invalid turn data"):
            await appserver.list_turn_page(InvalidApp(), "thread")

    async def test_appserver_closes_socket_when_initialize_fails(self):
        class FakeWebSocket:
            def __init__(self):
                self.closed = False

            async def send(self, message):
                pass

            async def recv(self):
                return '{"id":1,"error":{"message":"boom"}}'

            async def close(self):
                self.closed = True

        ws = FakeWebSocket()
        with mock.patch.object(
            appserver,
            "connect_websocket",
            mock.AsyncMock(return_value=ws),
        ):
            with self.assertRaises(ThreadctlError):
                async with appserver.AppServer("unix://", 1):
                    pass
        self.assertTrue(ws.closed)

    async def test_appserver_rejects_non_object_response(self):
        class FakeWebSocket:
            async def send(self, message):
                pass

            async def recv(self):
                return "[]"

        app = appserver.AppServer("unix://", 1)
        app.ws = FakeWebSocket()
        with self.assertRaisesRegex(ThreadctlError, "non-object"):
            await app.request("test")

    async def test_appserver_distinguishes_rpc_rejection(self):
        class FakeWebSocket:
            async def send(self, message):
                pass

            async def recv(self):
                return '{"id":1,"error":{"message":"rejected"}}'

        app = appserver.AppServer("unix://", 1)
        app.ws = FakeWebSocket()
        with self.assertRaisesRegex(AppServerResponseError, "rejected"):
            await app.request("test")

    async def test_appserver_timeout_names_limit_and_history_remedy(self):
        class FakeWebSocket:
            async def send(self, message):
                pass

        app = appserver.AppServer("unix://", 0)
        app.ws = FakeWebSocket()
        with self.assertRaisesRegex(
            ThreadctlError,
            r"timed out after 0s.*thread/turns/list.*concurrent readers.*--timeout",
        ):
            await app.request("thread/turns/list")

    async def test_appserver_ignores_server_request_with_matching_id(self):
        class FakeWebSocket:
            def __init__(self):
                self.messages = [
                    '{"id":1,"method":"item/tool/requestUserInput","params":{}}',
                    '{"id":1,"result":{"ok":true}}',
                ]

            async def send(self, message):
                pass

            async def recv(self):
                return self.messages.pop(0)

        app = appserver.AppServer("unix://", 1)
        app.ws = FakeWebSocket()
        self.assertEqual(await app.request("test"), {"ok": True})

    async def test_appserver_retains_notifications_seen_during_a_request(self):
        class FakeWebSocket:
            def __init__(self):
                self.messages = [
                    '{"method":"item/agentMessage/delta","params":{}}',
                    '{"method":"turn/started","params":{"threadId":"thread"}}',
                    '{"id":1,"result":{"ok":true}}',
                ]

            async def send(self, message):
                pass

            async def recv(self):
                return self.messages.pop(0)

        app = appserver.AppServer("unix://", 1)
        app.ws = FakeWebSocket()

        await app.request("test")

        self.assertEqual(
            [notification["method"] for notification in app.turn_notifications],
            ["turn/started"],
        )

    async def test_list_loaded_follows_pagination(self):
        calls = []

        class PagedApp:
            async def request(self, method, params):
                calls.append((method, params))
                if params.get("cursor") == "next":
                    return {"data": ["b"], "nextCursor": None}
                return {"data": ["a"], "nextCursor": "next"}

        self.assertEqual(await appserver.list_loaded(PagedApp()), ["a", "b"])
        self.assertEqual(calls[-1], ("thread/loaded/list", {"cursor": "next"}))

    async def test_list_loaded_rejects_repeated_cursor(self):
        class PagedApp:
            async def request(self, method, params):
                return {"data": [], "nextCursor": "same"}

        with self.assertRaisesRegex(ThreadctlError, "cursor"):
            await appserver.list_loaded(PagedApp())

    async def test_list_threads_passes_relationship_sort_and_limit(self):
        calls = []

        class ListApp:
            async def request(self, method, params):
                calls.append((method, params))
                return {
                    "data": [
                        {"id": "child", "status": {"type": "notLoaded"}},
                    ],
                    "nextCursor": None,
                }

        result = await appserver.list_threads(
            ListApp(),
            parent_thread_id="parent",
            limit=5,
            sort_key="created_at",
        )
        self.assertEqual([thread["id"] for thread in result], ["child"])
        self.assertEqual(
            calls,
            [
                (
                    "thread/list",
                    {
                        "limit": 5,
                        "sortKey": "created_at",
                        "sortDirection": "desc",
                        "modelProviders": [],
                        "parentThreadId": "parent",
                    },
                )
            ],
        )

    async def test_list_threads_follows_pagination_and_honors_limit(self):
        class PagedApp:
            async def request(self, method, params):
                if params.get("cursor") == "next":
                    return {
                        "data": [
                            {"id": "c", "status": {"type": "idle"}},
                            {"id": "d", "status": {"type": "idle"}},
                        ],
                        "nextCursor": "unused",
                    }
                return {
                    "data": [
                        {"id": "a", "status": {"type": "active"}},
                        {"id": "b", "status": {"type": "notLoaded"}},
                    ],
                    "nextCursor": "next",
                }

        result = await appserver.list_threads(PagedApp(), limit=3)
        self.assertEqual([thread["id"] for thread in result], ["a", "b", "c"])

    async def test_list_threads_zero_limit_reads_all_pages(self):
        calls = []

        class PagedApp:
            async def request(self, method, params):
                calls.append(params)
                if params.get("cursor") == "next":
                    return {
                        "data": [{"id": "b", "status": {"type": "idle"}}],
                        "nextCursor": None,
                    }
                return {
                    "data": [{"id": "a", "status": {"type": "idle"}}],
                    "nextCursor": "next",
                }

        result = await appserver.list_threads(
            PagedApp(), ancestor_thread_id="root", limit=0
        )
        self.assertEqual([thread["id"] for thread in result], ["a", "b"])
        self.assertEqual(calls[1]["cursor"], "next")
        self.assertTrue(all(call["ancestorThreadId"] == "root" for call in calls))

    async def test_list_threads_rejects_invalid_data_and_filters(self):
        class InvalidApp:
            async def request(self, method, params):
                return {"data": [{"id": "thread"}], "nextCursor": None}

        with self.assertRaisesRegex(ThreadctlError, "thread list data"):
            await appserver.list_threads(InvalidApp())
        with self.assertRaisesRegex(ThreadctlError, "mutually exclusive"):
            await appserver.list_threads(
                InvalidApp(),
                parent_thread_id="parent",
                ancestor_thread_id="ancestor",
            )

    async def test_list_threads_rejects_repeated_cursor(self):
        class PagedApp:
            async def request(self, method, params):
                return {"data": [], "nextCursor": "same"}

        with self.assertRaisesRegex(ThreadctlError, "cursor"):
            await appserver.list_threads(PagedApp(), limit=0)

    async def test_search_threads_passes_query_sort_and_limit(self):
        calls = []

        class SearchApp:
            async def request(self, method, params):
                calls.append((method, params))
                return {
                    "data": [
                        {
                            "thread": {"id": "thread", "status": {"type": "idle"}},
                            "snippet": "matching text",
                        }
                    ],
                    "nextCursor": None,
                }

        result = await appserver.search_threads(
            SearchApp(),
            "matching",
            limit=5,
            sort_key="updated_at",
        )
        self.assertEqual(result[0]["snippet"], "matching text")
        self.assertEqual(
            calls,
            [
                (
                    "thread/search",
                    {
                        "searchTerm": "matching",
                        "limit": 5,
                        "sortKey": "updated_at",
                        "sortDirection": "desc",
                        "sourceKinds": [],
                    },
                )
            ],
        )

    async def test_search_threads_pages_and_validates_results(self):
        class PagedApp:
            async def request(self, method, params):
                if params.get("cursor") == "next":
                    return {
                        "data": [
                            {
                                "thread": {"id": "b", "status": {"type": "idle"}},
                                "snippet": "second",
                            }
                        ],
                        "nextCursor": None,
                    }
                return {
                    "data": [
                        {
                            "thread": {"id": "a", "status": {"type": "idle"}},
                            "snippet": "first",
                        }
                    ],
                    "nextCursor": "next",
                }

        result = await appserver.search_threads(PagedApp(), "text", limit=0)
        self.assertEqual([match["thread"]["id"] for match in result], ["a", "b"])

        class InvalidApp:
            async def request(self, method, params):
                return {"data": [{"thread": {"id": "a"}}], "nextCursor": None}

        with self.assertRaisesRegex(ThreadctlError, "thread search data"):
            await appserver.search_threads(InvalidApp(), "text")
        with self.assertRaisesRegex(ThreadctlError, "must not be empty"):
            await appserver.search_threads(InvalidApp(), "  ")

    async def test_search_threads_rejects_repeated_cursor(self):
        class PagedApp:
            async def request(self, method, params):
                return {"data": [], "nextCursor": "same"}

        with self.assertRaisesRegex(ThreadctlError, "cursor"):
            await appserver.search_threads(PagedApp(), "text", limit=0)

    async def test_background_terminals_page_and_terminate_exact_process(self):
        calls = []

        class TerminalApp(FakeApp):
            async def request(self, method, params=None):
                calls.append((method, params))
                if method == "thread/backgroundTerminals/list":
                    if params.get("cursor") == "next":
                        return {
                            "data": [
                                {
                                    "processId": "43",
                                    "itemId": "item-b",
                                    "command": "sleep 2",
                                    "cwd": "/work",
                                }
                            ],
                            "nextCursor": None,
                        }
                    return {
                        "data": [
                            {
                                "processId": "42",
                                "itemId": "item-a",
                                "command": "sleep 1",
                                "cwd": "/work",
                            }
                        ],
                        "nextCursor": "next",
                    }
                if method == "thread/backgroundTerminals/terminate":
                    return {"terminated": params["processId"] == "42"}
                return await super().request(method, params)

        app = TerminalApp()
        terminals = await appserver.list_background_terminals(app, "thread", limit=0)
        self.assertEqual(
            [terminal["processId"] for terminal in terminals],
            ["42", "43"],
        )
        self.assertTrue(
            await appserver.terminate_background_terminal(
                app, "thread", "42", "item-a"
            )
        )
        self.assertFalse(
            await appserver.terminate_background_terminal(
                app, "thread", "43", "item-b"
            )
        )
        with self.assertRaisesRegex(ThreadStateError, "not found"):
            await appserver.terminate_background_terminal(
                app, "thread", "999999", "missing-item"
            )
        with self.assertRaisesRegex(ThreadStateError, "identity changed"):
            await appserver.terminate_background_terminal(
                app, "thread", "42", "stale-item"
            )
        self.assertIn(
            (
                "thread/backgroundTerminals/terminate",
                {"threadId": "thread", "processId": "42"},
            ),
            calls,
        )

    async def test_background_terminals_validate_data_and_cursor(self):
        class InvalidApp(FakeApp):
            async def request(self, method, params=None):
                if method == "thread/backgroundTerminals/list":
                    return {"data": [{"processId": "42"}], "nextCursor": None}
                return await super().request(method, params)

        with self.assertRaisesRegex(ThreadctlError, "background-terminal data"):
            await appserver.list_background_terminals(InvalidApp(), "thread")

        class RepeatedCursorApp(FakeApp):
            async def request(self, method, params=None):
                if method == "thread/backgroundTerminals/list":
                    return {"data": [], "nextCursor": "same"}
                return await super().request(method, params)

        with self.assertRaisesRegex(ThreadctlError, "cursor"):
            await appserver.list_background_terminals(
                RepeatedCursorApp(), "thread", limit=0
            )

    async def test_start_confirms_new_turn(self):
        app = FakeApp()
        result = await appserver.start_turn(app, "thread", "message")
        self.assertEqual(result["delivery"], "started")
        self.assertEqual(result["turnId"], "submission")
        self.assertEqual(result["clientMessageId"], app.client_message_id)
        self.assertNotIn("itemId", result)

    async def test_start_reports_race_into_active_turn(self):
        app = FakeApp(actual_turn_id="other-turn")
        result = await appserver.start_turn(app, "thread", "message")
        self.assertEqual(result["delivery"], "steered")
        self.assertEqual(result["turnId"], "other-turn")
        self.assertEqual(result["submittedTurnId"], "submission")

    async def test_start_confirmation_uses_recent_native_items(self):
        class PaginatedApp(FakeApp):
            async def request(self, method, params=None):
                if (
                    method == "thread/items/list"
                    and self.client_message_id is not None
                ):
                    self.calls.append((method, params))
                    return {
                        "data": [
                            {
                                "turnId": "submission",
                                "item": {
                                        "type": "userMessage",
                                        "id": "item",
                                        "clientId": self.client_message_id,
                                        "content": [],
                                },
                            }
                        ],
                        "nextCursor": None,
                    }
                return await super().request(method, params)

        app = PaginatedApp()
        result = await appserver.start_turn(app, "thread", "message")

        self.assertEqual(result["delivery"], "started")
        confirmation_calls = [
            params
            for method, params in app.calls
            if method == "thread/items/list"
        ]
        self.assertEqual(len(confirmation_calls), 1)
        self.assertNotIn("cursor", confirmation_calls[0])

    async def test_start_confirmation_falls_back_for_classic_history(self):
        class ClassicApp(FakeApp):
            async def request(self, method, params=None):
                if method == "thread/items/list":
                    raise AppServerResponseError(
                        {
                            "code": -32601,
                            "message": "thread/items/list is not supported yet",
                        }
                    )
                return await super().request(method, params)

        app = ClassicApp()
        result = await appserver.start_turn(app, "thread", "message")

        self.assertEqual(result["delivery"], "started")
        self.assertTrue(
            any(method == "thread/turns/list" for method, _ in app.calls)
        )

    async def test_start_confirmation_waits_for_bare_item_attribution(self):
        class BareItemApp(FakeApp):
            def __init__(self):
                super().__init__(actual_turn_id="other-turn")
                self.notified = False

            async def request(self, method, params=None):
                if (
                    method == "thread/items/list"
                    and self.client_message_id is not None
                ):
                    if not self.notified:
                        self.turn_notifications.append(
                            {
                                "method": "item/started",
                                "params": {
                                    "threadId": "thread",
                                    "turnId": "other-turn",
                                    "item": {
                                        "type": "userMessage",
                                        "clientId": self.client_message_id,
                                    },
                                },
                            }
                        )
                        self.notified = True
                    return {
                        "data": [
                            {
                                "type": "userMessage",
                                "id": "item",
                                "clientId": self.client_message_id,
                                "content": [],
                            }
                        ],
                        "nextCursor": None,
                    }
                if method == "thread/turns/list":
                    raise AppServerResponseError(
                        {"code": -32601, "message": "paginated_threads is not supported yet"}
                    )
                return await super().request(method, params)

        result = await appserver.start_turn(BareItemApp(), "thread", "message")

        self.assertEqual(result["delivery"], "steered")
        self.assertEqual(result["turnId"], "other-turn")

    async def test_start_confirmation_does_not_invent_bare_item_attribution(self):
        class BareItemApp(FakeApp):
            async def request(self, method, params=None):
                if (
                    method == "thread/items/list"
                    and self.client_message_id is not None
                ):
                    return {
                        "data": [
                            {
                                "type": "userMessage",
                                "id": "item",
                                "clientId": self.client_message_id,
                                "content": [],
                            }
                        ],
                        "nextCursor": None,
                    }
                if method == "thread/turns/list":
                    raise AppServerResponseError(
                        {"code": -32601, "message": "paginated_threads is not supported yet"}
                    )
                return await super().request(method, params)

        with self.assertRaises(DeliveryUncertain) as raised:
            await appserver.start_turn(
                BareItemApp(),
                "thread",
                "message",
                confirmation_timeout=0.01,
            )

        self.assertEqual(raised.exception.turn_id, "submission")

    async def test_start_refuses_known_active_thread(self):
        with self.assertRaises(ThreadStateError):
            await appserver.start_turn(FakeApp(status="active"), "thread", "message")

    async def test_start_marks_lost_response_uncertain(self):
        app = FakeApp()

        async def fail_after_send(method, params=None):
            if method == "turn/start":
                raise ThreadctlError("timed out")
            return await FakeApp.request(app, method, params)

        app.request = fail_after_send
        with self.assertRaises(DeliveryUncertain) as raised:
            await appserver.start_turn(app, "thread", "message")
        self.assertIsNone(raised.exception.turn_id)

    async def test_start_preserves_rpc_rejection(self):
        app = FakeApp()

        async def reject(method, params=None):
            if method == "turn/start":
                raise AppServerResponseError({"message": "rejected"})
            return await FakeApp.request(app, method, params)

        app.request = reject
        with self.assertRaises(AppServerResponseError):
            await appserver.start_turn(app, "thread", "message")

    async def test_start_marks_confirmation_failure_uncertain(self):
        app = FakeApp()
        original_request = app.request

        async def fail_confirmation(method, params=None):
            if method == "thread/items/list" and app.client_message_id is not None:
                raise ThreadctlError("history unavailable")
            return await original_request(method, params)

        app.request = fail_confirmation
        with self.assertRaises(DeliveryUncertain) as raised:
            await appserver.start_turn(app, "thread", "message")
        self.assertEqual(raised.exception.turn_id, "submission")

    async def test_notify_injects_one_agent_message_without_starting_a_turn(self):
        app = FakeApp()

        async def request(method, params=None):
            if method == "thread/inject_items":
                app.calls.append((method, params))
                return {}
            return await FakeApp.request(app, method, params)

        app.request = request
        result = await appserver.notify_thread(
            app,
            "thread",
            "coordinator",
            "Stream s has unread entries.",
        )

        self.assertEqual(result["outcome"], "accepted")
        method, params = app.calls[-1]
        self.assertEqual(method, "thread/inject_items")
        self.assertEqual(params["threadId"], "thread")
        self.assertEqual(
            params["items"],
            [
                {
                    "type": "agent_message",
                    "id": None,
                    "author": "coordinator",
                    "recipient": "thread",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "Stream s has unread entries.",
                        }
                    ],
                }
            ],
        )
        self.assertFalse(any(method == "turn/start" for method, _ in app.calls))

    async def test_notify_preserves_rejection_and_marks_other_failures_uncertain(self):
        app = FakeApp()

        async def reject(method, params=None):
            if method == "thread/inject_items":
                raise AppServerResponseError({"message": "rejected"})
            return await FakeApp.request(app, method, params)

        app.request = reject
        with self.assertRaises(AppServerResponseError):
            await appserver.notify_thread(app, "thread", "author", "message")

        async def fail(method, params=None):
            if method == "thread/inject_items":
                raise ThreadctlError("connection closed")
            return await FakeApp.request(app, method, params)

        app.request = fail
        with self.assertRaisesRegex(ThreadctlError, "outcome is uncertain"):
            await appserver.notify_thread(app, "thread", "author", "message")

    async def test_notify_requires_target_loaded_on_selected_server(self):
        app = FakeApp(loaded=False)

        with self.assertRaises(ThreadNotLoaded):
            await appserver.notify_thread(app, "thread", "author", "message")

        self.assertFalse(
            any(method == "thread/inject_items" for method, _ in app.calls)
        )

    async def test_wake_starts_an_empty_turn_and_confirms_its_identity(self):
        app = FakeApp()

        result = await appserver.wake_thread(app, "thread")

        self.assertEqual(result["outcome"], "confirmedStarted")
        self.assertEqual(result["turnId"], "submission")
        self.assertIn(
            ("turn/start", {"threadId": "thread", "input": []}),
            app.calls,
        )

    async def test_wake_is_a_successful_noop_for_an_active_thread(self):
        app = FakeApp(status="active", actual_turn_id="active-turn")

        result = await appserver.wake_thread(app, "thread")

        self.assertEqual(result["outcome"], "notSubmittedActive")
        self.assertEqual(result["turnId"], "active-turn")
        self.assertFalse(any(method == "turn/start" for method, _ in app.calls))

    async def test_wake_active_noop_survives_optional_turn_lookup_failure(self):
        app = FakeApp(status="active")
        original_request = app.request

        async def fail_turn_lookup(method, params=None):
            if method == "thread/turns/list":
                raise OSError("connection closed")
            return await original_request(method, params)

        app.request = fail_turn_lookup
        result = await appserver.wake_thread(app, "thread")

        self.assertEqual(
            result,
            {
                "threadId": "thread",
                "outcome": "notSubmittedActive",
                "observedStatus": "active",
            },
        )
        self.assertFalse(any(method == "turn/start" for method, _ in app.calls))

    async def test_wake_reports_not_loaded_without_resuming(self):
        app = FakeApp(loaded=False)

        result = await appserver.wake_thread(app, "thread")

        self.assertEqual(result["outcome"], "notLoaded")
        self.assertFalse(any(method == "thread/resume" for method, _ in app.calls))
        self.assertFalse(any(method == "turn/start" for method, _ in app.calls))

    async def test_wake_reports_rpc_rejection_and_uncertain_confirmation(self):
        app = FakeApp()

        async def reject(method, params=None):
            if method == "turn/start":
                raise AppServerResponseError({"message": "rejected"})
            return await FakeApp.request(app, method, params)

        app.request = reject
        rejected = await appserver.wake_thread(app, "thread")
        self.assertEqual(rejected["outcome"], "rejected")

        uncertain = await appserver.wake_thread(
            FakeApp(actual_turn_id="other-turn"),
            "thread",
            confirmation_timeout=0,
        )
        self.assertEqual(uncertain["outcome"], "uncertain")
        self.assertEqual(uncertain["turnId"], "submission")

    async def test_wake_confirmation_accepts_exact_started_notification(self):
        app = FakeApp()
        app.turn_notifications.append(
            {
                "method": "turn/started",
                "params": {
                    "threadId": "thread",
                    "turn": {"id": "turn", "status": "inProgress"},
                },
            }
        )

        result = await appserver.confirm_wake(app, "thread", "turn", 1)

        self.assertEqual(result["outcome"], "confirmedStarted")
        self.assertEqual(result["turnId"], "turn")

    async def test_wake_confirmation_does_not_claim_turn_completion(self):
        app = FakeApp(actual_turn_id="turn", turn_status="interrupted")

        result = await appserver.confirm_wake(app, "thread", "turn", 1)

        self.assertEqual(result["outcome"], "confirmedStarted")
        self.assertEqual(result["turnId"], "turn")
        self.assertEqual(result["observedStatus"], "interrupted")

    async def test_wake_confirmation_reports_terminal_error_notification(self):
        app = FakeApp()
        app.turn_notifications.append(
            {
                "method": "error",
                "params": {
                    "threadId": "thread",
                    "turnId": "turn",
                    "willRetry": False,
                    "error": {"message": "empty input rejected"},
                },
            }
        )

        result = await appserver.confirm_wake(app, "thread", "turn", 1)

        self.assertEqual(result["outcome"], "rejected")
        self.assertEqual(result["turnId"], "turn")

    async def test_wake_confirmation_reports_competing_active_turn(self):
        app = FakeApp(actual_turn_id="other-turn")
        with mock.patch.object(
            appserver.time,
            "monotonic",
            side_effect=[0.0, 0.0, 2.0, 2.0],
        ):
            result = await appserver.confirm_wake(app, "thread", "submitted", 1)

        self.assertEqual(result["outcome"], "uncertain")
        self.assertEqual(result["turnId"], "submitted")
        self.assertEqual(result["observedStatus"], "active")
        self.assertIn("another active turn was other-turn", result["reason"])

    async def test_steer_uses_expected_turn_id(self):
        app = FakeApp(status="active")
        result = await appserver.steer_turn(app, "thread", "turn", "message")
        self.assertEqual(result["delivery"], "steered")
        self.assertEqual(
            app.calls[-1][1]["expectedTurnId"],
            "turn",
        )

    async def test_steer_marks_lost_response_uncertain(self):
        app = FakeApp(status="active")

        async def fail_after_send(method, params=None):
            if method == "turn/steer":
                raise ThreadctlError("connection closed")
            return await FakeApp.request(app, method, params)

        app.request = fail_after_send
        with self.assertRaises(DeliveryUncertain) as raised:
            await appserver.steer_turn(app, "thread", "turn", "message")
        self.assertEqual(raised.exception.turn_id, "turn")

    async def test_steer_maps_native_turn_race_to_state_error(self):
        app = FakeApp(status="active")

        async def reject(method, params=None):
            if method == "turn/steer":
                raise AppServerResponseError(
                    {"message": "no active turn to steer"}
                )
            return await FakeApp.request(app, method, params)

        app.request = reject
        with self.assertRaisesRegex(ThreadStateError, "no active turn"):
            await appserver.steer_turn(app, "thread", "turn", "message")

    async def test_interrupt_is_turn_scoped_and_can_wait(self):
        app = FakeApp(status="active", actual_turn_id="turn")
        result = await appserver.interrupt_thread(
            app,
            "thread",
            "turn",
            wait=True,
        )
        self.assertEqual(result["status"], "interrupted")
        self.assertIn(
            ("turn/interrupt", {"threadId": "thread", "turnId": "turn"}),
            app.calls,
        )

    async def test_resume_loads_persisted_thread_without_turns(self):
        app = FakeApp(loaded=False)
        thread = await appserver.resume_thread(app, "thread", continue_goal=True)
        self.assertEqual(thread["id"], "thread")
        self.assertEqual(
            app.calls[-1],
            ("thread/resume", {"threadId": "thread", "excludeTurns": True}),
        )

    async def test_resume_requires_explicit_goal_continuation(self):
        app = FakeApp(loaded=False)
        with self.assertRaisesRegex(ThreadStateError, "--continue-goal"):
            await appserver.resume_thread(app, "thread")
        self.assertFalse(any(method == "thread/resume" for method, _ in app.calls))

    async def test_live_operations_require_selected_server_to_have_thread(self):
        with self.assertRaises(ThreadNotLoaded):
            await appserver.start_turn(FakeApp(loaded=False), "thread", "message")
