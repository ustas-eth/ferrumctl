import argparse
import errno
import os
import unittest
from unittest import mock

from codex_goalctl import appserver
from codex_goalctl.errors import GoalctlError, ServerUnavailable
from codex_goalctl.websocket import WebSocketAppServer


class SelectionTests(unittest.TestCase):
    def args(self, **changes):
        return argparse.Namespace(**({
            "thread_id": "worker", "codex_bin": "codex", "timeout": 2,
            "endpoint": None, "standalone": False,
        } | changes))

    def setUp(self):
        self.env = mock.patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.shared = mock.patch("codex_goalctl.websocket.WebSocketAppServer").start()
        self.standalone = mock.patch("codex_goalctl.appserver.AppServer").start()
        self.addCleanup(mock.patch.stopall)
        self.shared.return_value.request.side_effect = lambda method, params=None: (
            {"data": ["worker"], "nextCursor": None} if method == "thread/loaded/list" else {}
        )

    def test_default_reuses_server_holding_target(self):
        app = appserver.connect_appserver(self.args())
        self.assertIs(app, self.shared.return_value)
        self.shared.assert_called_once_with("unix://", 2)
        self.standalone.assert_not_called()
        self.assertEqual([call.args[0] for call in app.request.call_args_list], ["initialize", "thread/loaded/list"])

    def test_missing_server_falls_back_before_any_goal_operation(self):
        self.shared.side_effect = ServerUnavailable("missing socket")
        app = appserver.connect_appserver(self.args())
        self.assertIs(app, self.standalone.return_value)
        self.standalone.assert_called_once_with("codex", 2)

    def test_unloaded_target_closes_probe_and_uses_standalone(self):
        self.shared.return_value.request.side_effect = lambda method, params=None: (
            {"data": ["different"], "nextCursor": None} if method == "thread/loaded/list" else {}
        )
        app = appserver.connect_appserver(self.args())
        self.assertIs(app, self.standalone.return_value)
        self.shared.return_value.close.assert_called_once()
        self.assertFalse(any(call.args[0].startswith("thread/goal/") for call in self.shared.return_value.request.call_args_list))

    def test_loaded_pagination_keeps_same_connection(self):
        self.shared.return_value.request.side_effect = [
            {}, {"data": ["different"], "nextCursor": "page-2"},
            {"data": ["worker"], "nextCursor": None},
        ]
        app = appserver.connect_appserver(self.args())
        self.assertIs(app, self.shared.return_value)
        app.request.assert_called_with("thread/loaded/list", {"cursor": "page-2"})
        self.standalone.assert_not_called()

    def test_bad_or_failed_probe_never_falls_back(self):
        for result in ([], {"data": [1]}, {"data": [], "nextCursor": ""}, GoalctlError("timed out")):
            with self.subTest(result=result):
                self.shared.return_value.request.side_effect = [
                    {}, result,
                ]
                with self.assertRaises(GoalctlError):
                    appserver.connect_appserver(self.args())
        self.standalone.assert_not_called()

    def test_repeated_cursor_is_an_error(self):
        self.shared.return_value.request.side_effect = [
            {}, {"data": [], "nextCursor": "loop"}, {"data": [], "nextCursor": "loop"},
        ]
        with self.assertRaisesRegex(GoalctlError, "cursor"):
            appserver.connect_appserver(self.args())
        self.standalone.assert_not_called()

    def test_selected_connection_never_switches_after_write_failure(self):
        app = appserver.connect_appserver(self.args())
        app.request.side_effect = GoalctlError("lost response after sending")
        with self.assertRaises(GoalctlError):
            app.request("thread/goal/set", {"threadId": "worker"})
        self.standalone.assert_not_called()

    def test_explicit_endpoint_and_environment_skip_ownership_probe(self):
        for args, environment in ((self.args(endpoint="ws://other:123"), {}),
                                  (self.args(), {"CODEX_GOALCTL_ENDPOINT": "ws://other:123"})):
            with self.subTest(environment=environment):
                self.shared.reset_mock()
                with mock.patch.dict(os.environ, environment):
                    appserver.connect_appserver(args)
                self.shared.assert_called_once_with("ws://other:123", 2)
                self.shared.return_value.request.assert_called_once_with("initialize", mock.ANY)
        self.standalone.assert_not_called()

    def test_explicit_endpoint_failure_never_falls_back(self):
        self.shared.side_effect = ServerUnavailable("missing socket")
        with self.assertRaises(ServerUnavailable):
            appserver.connect_appserver(self.args(endpoint="unix://"))
        self.standalone.assert_not_called()

    def test_standalone_overrides_environment_without_probing(self):
        with mock.patch.dict(os.environ, {"CODEX_GOALCTL_ENDPOINT": "unix://"}):
            appserver.connect_appserver(self.args(standalone=True))
        self.shared.assert_not_called()
        self.standalone.assert_called_once()

    def test_conflicting_explicit_choices_are_rejected(self):
        with self.assertRaisesRegex(GoalctlError, "mutually exclusive"):
            appserver.connect_appserver(self.args(standalone=True, endpoint="unix://"))
        self.shared.assert_not_called()
        self.standalone.assert_not_called()


class AvailabilityTests(unittest.TestCase):
    def test_only_missing_and_refused_sockets_are_unavailable(self):
        for code in (errno.ENOENT, errno.ECONNREFUSED, errno.EACCES, errno.ENOTSOCK):
            with self.subTest(code=code):
                with mock.patch("codex_goalctl.websocket.unix_connect", side_effect=OSError(code, "fixture")):
                    with self.assertRaises(GoalctlError) as raised:
                        WebSocketAppServer("unix://", 1)
                self.assertEqual(isinstance(raised.exception, ServerUnavailable), code in {errno.ENOENT, errno.ECONNREFUSED})
