import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from streamctl import cli, parser, state


class EntryInputTests(unittest.TestCase):
    def run_pipe(self, path, stream, payload):
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
               "PYTHONIOENCODING": "utf-8:surrogateescape"}
        return subprocess.run(
            [sys.executable, "-m", "streamctl.cli", "append", stream, "--stdin",
             "--author", "worker", "--state", str(path), "--json"],
            input=payload, capture_output=True, env=env, timeout=5,
        )

    def test_exactly_one_entry_source_is_required(self):
        for suffix in ([], ["text", "--stdin"]):
            with self.subTest(suffix=suffix), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    parser.build_parser().parse_args(["append", "stream", *suffix])

    def test_stdin_preserves_text_and_supports_replies(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "streams.sqlite3"
            stream = state.create_stream(path)["streamId"]
            state.append_entry(path, stream, "other", "first")
            text = '  Reply\n--author another $(touch should-not-exist)\n'
            with mock.patch("sys.stdin", io.StringIO(text)), redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(["append", stream, "--stdin", "--author", "worker",
                                           "--reply-to", "1", "--state", str(path)]), 0)
            entries = state.list_entries(path, stream)["entries"]
            self.assertEqual(entries[1]["text"], text)
            self.assertEqual(entries[1]["author"], "worker")
            self.assertEqual(entries[1]["replyTo"], 1)

    def test_invalid_stdin_never_opens_or_initializes_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.sqlite3"
            for source in (io.StringIO(""), io.StringIO(" \n"), mock.Mock(isatty=lambda: True),
                           mock.Mock(isatty=lambda: False, read=mock.Mock(side_effect=UnicodeError("invalid")))):
                with (
                    self.subTest(source=source),
                    mock.patch("sys.stdin", source),
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()),
                ):
                    self.assertEqual(cli.main(["append", "stream", "--stdin", "--author", "worker",
                                               "--state", str(path)]), 1)
                self.assertFalse(path.exists())

    def test_invalid_byte_pipe_is_rejected_before_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "streams.sqlite3"
            stream = state.create_stream(path)["streamId"]
            state.append_entry(path, stream, "other", "existing entry")
            before = state.list_entries(path, stream)
            missing = Path(directory) / "missing.sqlite3"
            for selected in (path, missing):
                for payload in (b"invalid \xff\n", b"truncated \xe2\x82"):
                    with self.subTest(path=selected, payload=payload):
                        proc = self.run_pipe(selected, stream, payload)
                        self.assertEqual(proc.returncode, 1)
                        self.assertIn(b"could not read entry text from standard input", proc.stderr)
                        self.assertNotIn(b"Traceback", proc.stderr)
                        self.assertEqual(proc.stdout, b"")
            self.assertFalse(missing.exists())
            self.assertEqual(state.list_entries(path, stream), before)

    def test_byte_pipe_preserves_unicode_and_line_endings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "streams.sqlite3"
            stream = state.create_stream(path)["streamId"]
            text = "  Caf\u00e9 \U0001f680\r\nsecond\rthird\n"
            proc = self.run_pipe(path, stream, text.encode("utf-8"))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            entry = state.list_entries(path, stream)["entries"][0]
            self.assertEqual(entry["text"], text)
