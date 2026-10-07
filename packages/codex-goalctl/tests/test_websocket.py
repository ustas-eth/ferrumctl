import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from codex_goalctl.appserver import connect_appserver
from codex_goalctl.errors import GoalctlError
from codex_goalctl.websocket import WebSocketAppServer


class WebSocketTests(unittest.TestCase):
    def connect(self, endpoint="unix://", timeout=2):
        ws = mock.Mock()
        ws.recv.side_effect = [json.dumps({"id": 1, "result": {}})]
        with mock.patch("codex_goalctl.websocket.unix_connect", return_value=ws) as unix:
            with mock.patch("codex_goalctl.websocket.connect", return_value=ws) as tcp:
                app = connect_appserver(argparse.Namespace(endpoint=endpoint, timeout=timeout))
        return app, ws, unix, tcp

    def test_default_unix_endpoint_uses_codex_home(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict("os.environ", {"CODEX_HOME": directory}):
                app, ws, unix, tcp = self.connect()
        self.assertEqual(unix.call_args.args[0], str(Path(directory) / "app-server-control/app-server-control.sock"))
        tcp.assert_not_called()
        self.assertEqual([json.loads(call.args[0])["method"] for call in ws.send.call_args_list], ["initialize", "initialized"])
        app.close()
        ws.close.assert_called_once()

    def test_explicit_unix_and_websocket_endpoints(self):
        for endpoint in ("unix://relative.sock", "ws://localhost:1234", "wss://localhost/rpc"):
            with self.subTest(endpoint=endpoint):
                app, _, unix, tcp = self.connect(endpoint)
                if endpoint.startswith("unix://"):
                    self.assertEqual(unix.call_args.args[0], str(Path("relative.sock").resolve()))
                    tcp.assert_not_called()
                else:
                    self.assertEqual(tcp.call_args.args[0], endpoint)
                    unix.assert_not_called()
                app.close()

    def test_rpc_ignores_notifications_requests_and_unrelated_responses(self):
        app, ws, _, _ = self.connect()
        ws.recv.side_effect = [
            json.dumps({"id": 2, "method": "server/ping"}),
            json.dumps({"method": "thread/goal/updated", "params": {}}),
            json.dumps({"id": 3, "result": {}}),
            json.dumps({"id": 2, "result": {"cleared": True}}),
        ]
        self.assertEqual(app.request("thread/goal/clear", {"threadId": "test"}), {"cleared": True})
        self.assertEqual(json.loads(ws.send.call_args.args[0]), {
            "id": 2, "method": "thread/goal/clear", "params": {"threadId": "test"},
        })
        self.assertEqual(ws.recv.call_count, 5)
        app.close()

    def test_rpc_rejections_preserve_parent_ownership_guidance(self):
        app, ws, _, _ = self.connect()
        for method, expected in (("thread/goal/set", "native parent"), ("thread/goal/get", "direct app-server input")):
            with self.subTest(method=method):
                ws.recv.side_effect = [json.dumps({"id": app.next_id, "error": {
                    "message": "direct app-server input is not allowed for multi-agent v2 sub-agents",
                }})]
                with self.assertRaisesRegex(GoalctlError, expected):
                    app.request(method, {"threadId": "test"})
        app.close()

    def test_bad_responses_are_errors(self):
        for response, expected in (("[]", "non-object"), ("{", "invalid JSON"), ('{"id": 2}', "no result")):
            with self.subTest(response=response):
                app, ws, _, _ = self.connect()
                ws.recv.side_effect = [response]
                with self.assertRaisesRegex(GoalctlError, expected):
                    app.request("thread/goal/get", {})
                app.close()

    def test_timeout_does_not_retry_or_fall_back(self):
        app, ws, _, _ = self.connect()
        ws.recv.side_effect = TimeoutError
        with mock.patch("codex_goalctl.appserver.AppServer") as standalone:
            with self.assertRaisesRegex(GoalctlError, "timed out"):
                app.request("thread/goal/set", {"threadId": "test"})
        self.assertEqual(ws.send.call_count, 3)
        standalone.assert_not_called()
        app.close()

    def test_notifications_do_not_reset_request_deadline(self):
        app, ws, _, _ = self.connect(timeout=2)
        ws.recv.reset_mock()
        ws.recv.side_effect = [json.dumps({"method": "event"}), json.dumps({"id": 2, "result": {}})]
        with mock.patch("codex_goalctl.websocket.time.monotonic", side_effect=[0, 0.5, 1.5]):
            self.assertEqual(app.request("thread/goal/get", {}), {})
        self.assertEqual(ws.recv.call_args_list, [mock.call(timeout=1.5), mock.call(timeout=0.5)])
        app.close()

    def test_connection_failure_never_starts_a_standalone_server(self):
        with mock.patch("codex_goalctl.websocket.unix_connect", side_effect=OSError("missing socket")):
            with mock.patch("codex_goalctl.appserver.AppServer") as standalone:
                with self.assertRaisesRegex(GoalctlError, "could not connect"):
                    connect_appserver(argparse.Namespace(endpoint="unix://", timeout=1))
        standalone.assert_not_called()

    def test_invalid_endpoint_is_rejected_before_connecting(self):
        with mock.patch("codex_goalctl.websocket.connect") as tcp:
            with mock.patch("codex_goalctl.websocket.unix_connect") as unix:
                for endpoint in ("", "stdio://", "https://localhost", "/tmp/socket"):
                    with self.subTest(endpoint=endpoint):
                        with self.assertRaisesRegex(GoalctlError, "endpoint must"):
                            WebSocketAppServer(endpoint, 1)
        tcp.assert_not_called()
        unix.assert_not_called()

    def test_initialization_failure_closes_connection(self):
        ws = mock.Mock()
        ws.recv.return_value = json.dumps({"id": 1, "error": {"message": "rejected"}})
        with mock.patch("codex_goalctl.websocket.unix_connect", return_value=ws):
            with self.assertRaisesRegex(GoalctlError, "rejected"):
                connect_appserver(argparse.Namespace(endpoint="unix://", timeout=1))
        ws.close.assert_called_once()
