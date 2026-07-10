import contextlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from codex_threadctl import appserver
from codex_threadctl.errors import ThreadctlError


class FakeApp:
    def __init__(self, *, loaded=True, status="idle", goal=None, turn_status="completed"):
        self.loaded = loaded
        self.status = status
        self.goal = goal
        self.turn_status = turn_status
        self.calls = []

    async def request(self, method, params=None):
        self.calls.append((method, params))
        if method == "thread/loaded/list":
            return {"data": ["thread"] if self.loaded else [], "nextCursor": None}
        if method == "thread/read":
            return {"thread": {"id": "thread", "status": {"type": self.status}}}
        if method == "thread/turns/list":
            return {
                "data": [{"id": "turn", "status": self.turn_status, "items": []}],
                "nextCursor": None,
            }
        if method == "thread/goal/get":
            return {"goal": self.goal}
        if method in {"turn/interrupt", "thread/compact/start"}:
            return {}
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
        with mock.patch.object(appserver, "connect_websocket", mock.AsyncMock(return_value=ws)):
            with self.assertRaises(ThreadctlError):
                async with appserver.AppServer("unix://", 1):
                    pass
        self.assertTrue(ws.closed)

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

    async def test_interrupt_submits_current_turn_id(self):
        app = FakeApp(status="active", turn_status="inProgress")
        result = await appserver.interrupt_thread(app, "thread")
        self.assertEqual(result["turnId"], "turn")
        self.assertEqual(
            app.calls[-1],
            ("turn/interrupt", {"threadId": "thread", "turnId": "turn"}),
        )

    async def test_interrupt_refuses_idle_thread(self):
        with self.assertRaisesRegex(ThreadctlError, "no active turn"):
            await appserver.interrupt_thread(FakeApp(status="idle"), "thread")

    async def test_compact_refuses_active_turn(self):
        with self.assertRaisesRegex(ThreadctlError, "would replace"):
            await appserver.compact_thread(FakeApp(status="active"), "thread")

    async def test_compact_refuses_active_goal(self):
        app = FakeApp(status="idle", goal={"status": "active"})
        with self.assertRaisesRegex(ThreadctlError, "pause it"):
            await appserver.compact_thread(app, "thread")

    async def test_compact_submits_for_loaded_idle_thread(self):
        app = FakeApp(status="idle", goal={"status": "paused"})
        result = await appserver.compact_thread(app, "thread")
        self.assertEqual(result, {"threadId": "thread", "status": "started"})
        self.assertEqual(
            app.calls[-1],
            ("thread/compact/start", {"threadId": "thread"}),
        )

    async def test_live_operations_require_selected_server_to_have_thread(self):
        with self.assertRaisesRegex(ThreadctlError, "not loaded"):
            await appserver.compact_thread(FakeApp(loaded=False), "thread")
