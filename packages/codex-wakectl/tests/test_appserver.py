from __future__ import annotations

import contextlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from codex_wakectl import appserver
from codex_wakectl import cli
from codex_wakectl.errors import WakeDeferred


class AppServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_active_status_is_running(self) -> None:
        self.assertTrue(cli.thread_is_active({"type": "active"}))
        self.assertFalse(cli.thread_is_active({"type": "idle"}))
        self.assertFalse(cli.thread_is_active({"type": "notLoaded"}))
        self.assertFalse(cli.thread_is_active({"type": "systemError"}))

    async def test_send_turn_refuses_active_thread_without_guard_bypass(self) -> None:
        class FakeApp:
            async def request(self, method: str, params=None):
                if method == "thread/loaded/list":
                    return {"data": ["thread"], "nextCursor": None}
                if method == "thread/read":
                    return {"thread": {"status": {"type": "active", "activeFlags": []}}}
                raise AssertionError(f"unexpected method: {method}")

        with self.assertRaises(cli.WakectlError) as caught:
            await cli.send_turn(FakeApp(), "thread", "message")

        message = str(caught.exception)
        self.assertIn("refusing to send without --allow-active", message)
        self.assertNotIn("overlap", message)

    async def test_send_turn_treats_system_error_as_failure(self) -> None:
        class FakeApp:
            async def request(self, method: str, params=None):
                if method == "thread/loaded/list":
                    return {"data": ["thread"], "nextCursor": None}
                if method == "thread/read":
                    return {"thread": {"status": {"type": "systemError"}}}
                raise AssertionError(f"unexpected method: {method}")

        with self.assertRaises(cli.WakectlError) as caught:
            await cli.send_turn(FakeApp(), "thread", "message", allow_active=True)

        self.assertNotIsInstance(caught.exception, WakeDeferred)
        self.assertIn("thread status is systemError", str(caught.exception))

    async def test_default_endpoint_is_absolute_with_relative_codex_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with (
                contextlib.chdir(tmp),
                mock.patch.dict(os.environ, {"CODEX_HOME": "relative-home"}),
            ):
                endpoint = appserver.normalize_endpoint("unix://")

        expected = Path(tmp) / "relative-home/app-server-control/app-server-control.sock"
        self.assertEqual(endpoint, f"unix://{expected}")

    async def test_appserver_closes_socket_when_initialize_fails(self) -> None:
        class FakeWebSocket:
            def __init__(self) -> None:
                self.closed = False

            async def send(self, message: str) -> None:
                pass

            async def recv(self) -> str:
                return '{"id":1,"error":{"message":"boom"}}'

            async def close(self) -> None:
                self.closed = True

        ws = FakeWebSocket()

        async def fake_connect(endpoint: str) -> FakeWebSocket:
            return ws

        with mock.patch.object(appserver, "connect_websocket", fake_connect):
            with self.assertRaises(cli.WakectlError):
                async with cli.AppServer("unix://", 1):
                    pass

        self.assertTrue(ws.closed)

    async def test_interrupt_uses_active_turn_id(self) -> None:
        class FakeApp:
            def __init__(self) -> None:
                self.interrupt_params = None

            async def request(self, method: str, params=None):
                if method == "thread/loaded/list":
                    return {"data": ["thread"], "nextCursor": None}
                if method == "thread/read":
                    return {"thread": {"status": {"type": "active", "activeFlags": []}}}
                if method == "thread/turns/list":
                    return {"data": [{"id": "turn-1", "status": "inProgress"}]}
                if method == "turn/interrupt":
                    self.interrupt_params = params
                    return {}
                raise AssertionError(f"unexpected method: {method}")

        app = FakeApp()
        result = await cli.interrupt_turn(app, "thread")

        self.assertEqual(
            app.interrupt_params,
            {"threadId": "thread", "turnId": "turn-1"},
        )
        self.assertEqual(result["status"], "interrupted")

    async def test_interrupt_does_not_fall_back_to_startup_interrupt(self) -> None:
        class FakeApp:
            async def request(self, method: str, params=None):
                if method == "thread/loaded/list":
                    return {"data": ["thread"], "nextCursor": None}
                if method == "thread/read":
                    return {"thread": {"status": {"type": "active"}}}
                if method == "thread/turns/list":
                    return {"data": [{"id": "turn-1", "status": "completed"}]}
                if method == "turn/interrupt":
                    raise AssertionError("startup interrupt must not be sent")
                raise AssertionError(f"unexpected method: {method}")

        with self.assertRaises(cli.WakectlError) as caught:
            await cli.interrupt_turn(FakeApp(), "thread")

        self.assertIn("active turn id is unavailable", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
