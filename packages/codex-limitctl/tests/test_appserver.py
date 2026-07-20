from __future__ import annotations

import json
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from codex_limitctl.appserver import AppServer, read_rate_limits
from codex_limitctl.errors import LimitctlError


SERVER_HEADER = """\
#!/usr/bin/env python3
import json
import sys
import time

for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    if method == "initialized":
        continue
    request_id = message["id"]
"""


class AppServerTests(unittest.TestCase):
    def make_server(self, directory: str, body: str) -> Path:
        path = Path(directory) / "fake-codex"
        path.write_text(
            SERVER_HEADER + textwrap.indent(textwrap.dedent(body).lstrip(), "    ")
        )
        path.chmod(0o755)
        return path

    def test_reads_rate_limits_after_initialization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.make_server(
                tmp,
                """
                if method == "initialize":
                    print(json.dumps({"id": request_id, "result": {}}), flush=True)
                elif method == "account/rateLimits/read":
                    assert "params" not in message
                    print(json.dumps({
                        "id": request_id,
                        "result": {"rateLimits": {"limitId": "codex"}},
                    }), flush=True)
                else:
                    raise RuntimeError(method)
                """,
            )
            result = read_rate_limits(str(path), 2.0)

        self.assertEqual(result, {"rateLimits": {"limitId": "codex"}})

    def test_ignores_notifications_while_waiting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.make_server(
                tmp,
                """
                print(json.dumps({"method": "account/rateLimits/updated"}), flush=True)
                print(json.dumps({"id": request_id, "result": {"ok": True}}), flush=True)
                """,
            )
            app = AppServer(str(path), 2.0)
            try:
                result = app.request("initialize", {})
            finally:
                app.close()

        self.assertEqual(result, {"ok": True})

    def test_rejects_non_object_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.make_server(tmp, "print('[]', flush=True)\n")
            app = AppServer(str(path), 2.0)
            try:
                with self.assertRaisesRegex(LimitctlError, "non-object"):
                    app.request("initialize", {})
            finally:
                app.close()

    def test_invalid_json_does_not_echo_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.make_server(tmp, "print('SECRET-RESET-CREDIT {', flush=True)\n")
            app = AppServer(str(path), 2.0)
            try:
                with self.assertRaises(LimitctlError) as raised:
                    app.request("initialize", {})
            finally:
                app.close()

        self.assertEqual(str(raised.exception), "app-server returned invalid JSON")
        self.assertNotIn("SECRET-RESET-CREDIT", str(raised.exception))

    def test_rpc_error_omits_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.make_server(
                tmp,
                """
                print(json.dumps({
                    "id": request_id,
                    "error": {
                        "code": -32001,
                        "message": "not logged in",
                        "data": {
                            "credits": [{"id": "SECRET-PAID-CREDIT"}],
                            "rateLimitResetCredits": {
                                "credits": [{"id": "SECRET-RESET-CREDIT"}]
                            },
                            "usage": {"lifetimeTokens": "SECRET-ANALYTICS"},
                        },
                    },
                }), flush=True)
                """,
            )
            app = AppServer(str(path), 2.0)
            try:
                with self.assertRaises(LimitctlError) as raised:
                    app.request("initialize", {})
            finally:
                app.close()

        self.assertEqual(
            str(raised.exception),
            "app-server error -32001: not logged in",
        )
        self.assertNotIn("SECRET-PAID-CREDIT", str(raised.exception))
        self.assertNotIn("SECRET-RESET-CREDIT", str(raised.exception))
        self.assertNotIn("SECRET-ANALYTICS", str(raised.exception))

    def test_stderr_is_not_echoed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.make_server(
                tmp,
                """
                print("SECRET-RESET-CREDIT", file=sys.stderr, flush=True)
                raise SystemExit(2)
                """,
            )
            app = AppServer(str(path), 2.0)
            try:
                with self.assertRaises(LimitctlError) as raised:
                    app.request("initialize", {})
            finally:
                app.close()

        self.assertIn("app-server exited", str(raised.exception))
        self.assertIn("diagnostics omitted", str(raised.exception))
        self.assertNotIn("SECRET-RESET-CREDIT", str(raised.exception))

    def test_broken_stdin_is_transport_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fake-codex"
            path.write_text("#!/usr/bin/env python3\n")
            path.chmod(0o755)
            app = AppServer(str(path), 2.0)
            app.proc.wait(timeout=2)
            try:
                with self.assertRaisesRegex(LimitctlError, "failed to write"):
                    app.request("initialize", {})
            finally:
                app.close()

    def test_timeout_bounds_initialization_and_read_together(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.make_server(
                tmp,
                """
                time.sleep(0.6)
                if method == "initialize":
                    print(json.dumps({"id": request_id, "result": {}}), flush=True)
                else:
                    print(json.dumps({
                        "id": request_id,
                        "result": {
                            "rateLimits": {
                                "limitId": "codex",
                                "primary": None,
                                "secondary": None,
                            }
                        },
                    }), flush=True)
                """,
            )
            started = time.monotonic()
            with self.assertRaisesRegex(LimitctlError, "timed out"):
                read_rate_limits(str(path), 0.9)
            elapsed = time.monotonic() - started

        self.assertLess(elapsed, 1.15)


if __name__ == "__main__":
    unittest.main()
