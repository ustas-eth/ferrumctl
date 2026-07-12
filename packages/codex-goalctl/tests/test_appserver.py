from __future__ import annotations

import argparse
import tempfile
import textwrap
import unittest
from pathlib import Path

from codex_goalctl.appserver import connect_appserver
from codex_goalctl.errors import GoalctlError


SERVER_HEADER = """\
#!/usr/bin/env python3
import json
import sys

for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    if method == "initialized":
        continue
    request_id = message["id"]
    if method == "initialize":
        print(json.dumps({"id": request_id, "result": {}}), flush=True)
        continue
"""


class AppServerTests(unittest.TestCase):
    def make_server(self, directory: str, body: str) -> Path:
        path = Path(directory) / "fake-codex"
        body = textwrap.indent(textwrap.dedent(body).lstrip(), "    ")
        path.write_text(SERVER_HEADER + body)
        path.chmod(0o755)
        return path

    def connect(self, path: Path):
        return connect_appserver(argparse.Namespace(codex_bin=str(path), timeout=2.0))

    def test_ignores_server_request_with_matching_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.make_server(
                tmp,
                """
                print(json.dumps({"id": request_id, "method": "server/ping"}), flush=True)
                print(json.dumps({
                    "id": request_id,
                    "result": {"goal": {"status": "active", "objective": "test"}},
                }), flush=True)
                """,
            )
            app = self.connect(path)
            try:
                result = app.request("thread/goal/get", {"threadId": "thread"})
            finally:
                app.close()

        self.assertEqual(result["goal"]["objective"], "test")

    def test_rejects_non_object_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.make_server(tmp, "print('[]', flush=True)\n")
            app = self.connect(path)
            try:
                with self.assertRaisesRegex(GoalctlError, "non-object"):
                    app.request("thread/goal/get", {"threadId": "thread"})
            finally:
                app.close()

    def test_rejects_response_without_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.make_server(
                tmp,
                'print(json.dumps({"id": request_id}), flush=True)\n',
            )
            app = self.connect(path)
            try:
                with self.assertRaisesRegex(GoalctlError, "has no result"):
                    app.request("thread/goal/get", {"threadId": "thread"})
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
