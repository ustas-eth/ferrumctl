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
        if method == "turn/start":
            self.client_message_id = params["clientUserMessageId"]
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
    async def test_default_endpoint_uses_codex_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            with (
                contextlib.chdir(tmp),
                mock.patch.dict(os.environ, {"CODEX_HOME": "relative-home"}),
            ):
                result = appserver.resolve_unix_endpoint("unix://")
        expected = Path(tmp) / "relative-home/app-server-control/app-server-control.sock"
        self.assertEqual(result, str(expected))

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

    async def test_start_confirms_new_turn(self):
        result = await appserver.start_turn(FakeApp(), "thread", "message")
        self.assertEqual(result["delivery"], "started")
        self.assertEqual(result["turnId"], "submission")

    async def test_start_reports_race_into_active_turn(self):
        app = FakeApp(actual_turn_id="other-turn")
        result = await appserver.start_turn(app, "thread", "message")
        self.assertEqual(result["delivery"], "steered")
        self.assertEqual(result["turnId"], "other-turn")
        self.assertEqual(result["submittedTurnId"], "submission")

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
            if method == "thread/turns/list" and app.client_message_id is not None:
                raise ThreadctlError("history unavailable")
            return await original_request(method, params)

        app.request = fail_confirmation
        with self.assertRaises(DeliveryUncertain) as raised:
            await appserver.start_turn(app, "thread", "message")
        self.assertEqual(raised.exception.turn_id, "submission")

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
        thread = await appserver.resume_thread(app, "thread")
        self.assertEqual(thread["id"], "thread")
        self.assertEqual(
            app.calls[-1],
            ("thread/resume", {"threadId": "thread", "excludeTurns": True}),
        )

    async def test_live_operations_require_selected_server_to_have_thread(self):
        with self.assertRaises(ThreadNotLoaded):
            await appserver.start_turn(FakeApp(loaded=False), "thread", "message")
