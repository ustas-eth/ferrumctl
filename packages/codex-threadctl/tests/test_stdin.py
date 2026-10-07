import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from codex_threadctl import communication_commands, parser
from codex_threadctl.errors import ThreadctlError


class MessageInputTests(unittest.IsolatedAsyncioTestCase):
    def test_exactly_one_message_source_is_required(self):
        for operation in ("send", "input"):
            for suffix in ([], ["text", "--stdin"]):
                with self.subTest(operation=operation, suffix=suffix), redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        parser.build_parser().parse_args([operation, "thread", *suffix])

    async def test_stdin_preserves_text_and_message_role(self):
        text = '  A report\n--endpoint elsewhere $(touch should-not-exist)\n'
        for operation in ("send", "input"):
            args = parser.build_parser().parse_args(
                [operation, "thread", "--stdin", "--json", *(["--from", "worker"] if operation == "send" else [])]
            )
            context = mock.MagicMock()
            context.__aenter__ = mock.AsyncMock(return_value="app")
            context.__aexit__ = mock.AsyncMock(return_value=None)
            result = ({"outcome": "accepted", "itemId": "message", "author": "worker"}
                      if operation == "send" else {"delivery": "started", "turnId": "turn"})
            function = "send_message" if operation == "send" else "start_turn"
            with (
                mock.patch.object(communication_commands, "AppServer", return_value=context),
                mock.patch.object(communication_commands, "resolve_thread_reference", new=mock.AsyncMock(return_value="thread")),
                mock.patch.object(communication_commands, function, new=mock.AsyncMock(return_value=result)) as deliver,
                mock.patch("sys.stdin", io.StringIO(text)),
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(await args.func(args), 0)
            self.assertEqual(deliver.call_args.args[-1], text)

    async def test_invalid_stdin_fails_before_connecting(self):
        for operation in ("send", "input"):
            args = parser.build_parser().parse_args([operation, "thread", "--stdin"])
            for source in (io.StringIO(""), io.StringIO(" \n\t"), mock.Mock(isatty=lambda: True)):
                with (
                    self.subTest(operation=operation, source=source),
                    mock.patch("sys.stdin", source),
                    mock.patch.object(communication_commands, "AppServer") as app,
                ):
                    with self.assertRaises(ThreadctlError):
                        await args.func(args)
                    app.assert_not_called()

    def test_read_failures_have_a_clear_error(self):
        args = parser.build_parser().parse_args(["send", "thread", "--stdin"])
        for failure in (OSError("closed"), UnicodeError("invalid encoding")):
            source = mock.Mock(isatty=lambda: False, read=mock.Mock(side_effect=failure))
            with mock.patch("sys.stdin", source), self.assertRaisesRegex(ThreadctlError, "could not read"):
                communication_commands.message_text(args)

    def test_invalid_byte_pipe_is_rejected_before_connecting(self):
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
               "PYTHONIOENCODING": "utf-8:surrogateescape"}
        with tempfile.TemporaryDirectory() as directory:
            endpoint = f"unix://{directory}/absent.sock"
            for operation in ("send", "input"):
                for payload in (b"invalid \xff\n", b"truncated \xe2\x82"):
                    with self.subTest(operation=operation, payload=payload):
                        argv = [sys.executable, "-m", "codex_threadctl.cli", operation,
                                "thread", "--stdin", "--endpoint", endpoint, "--json"]
                        if operation == "send":
                            argv += ["--from", "worker"]
                        proc = subprocess.run(argv, input=payload, capture_output=True,
                                              env=env, timeout=5)
                        self.assertEqual(proc.returncode, 1)
                        error = json.loads(proc.stdout)["error"]
                        self.assertEqual(error["message"], "could not read message text from standard input")
                        self.assertNotIn(b"Traceback", proc.stderr)
