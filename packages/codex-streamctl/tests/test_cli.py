import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from codex_streamctl import cli, parser


class ParserTests(unittest.TestCase):
    def test_version(self):
        with redirect_stdout(io.StringIO()) as output:
            with self.assertRaisesRegex(SystemExit, "0"):
                parser.build_parser().parse_args(["--version"])
        self.assertEqual(output.getvalue(), "codex-streamctl 0.1.4\n")

    def test_global_options_work_after_subcommand(self):
        args = parser.build_parser().parse_args(
            ["list", "stream", "--state", "/tmp/state", "--json"]
        )
        self.assertEqual(args.state, Path("/tmp/state"))
        self.assertTrue(args.json)

    def test_list_identity_is_resolved_when_the_command_runs(self):
        args = parser.build_parser().parse_args(["list", "stream"])
        self.assertIsNone(args.reader)


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "streams.sqlite3"

    def run_cli(self, *argv, env=None):
        stdout = io.StringIO()
        stderr = io.StringIO()
        environment = {} if env is None else env
        with (
            mock.patch.dict("os.environ", environment, clear=True),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            status = cli.main([*argv, "--state", str(self.path)])
        return status, stdout.getvalue(), stderr.getvalue()

    def test_create_append_list_and_ack(self):
        status, output, _ = self.run_cli("create", "--label", "review")
        self.assertEqual(status, 0)
        stream_id = output.strip()

        status, output, _ = self.run_cli(
            "append",
            stream_id,
            "--author",
            "a",
            "first",
        )
        self.assertEqual((status, output), (0, "1\n"))
        self.run_cli(
            "append",
            stream_id,
            "--author",
            "b",
            "--reply-to",
            "1",
            "second\nline",
        )

        status, output, _ = self.run_cli(
            "list",
            stream_id,
            "--reader",
            "b",
            "--json",
        )
        payload = json.loads(output)
        self.assertEqual(status, 0)
        self.assertEqual(payload["label"], "review")
        self.assertEqual(
            [entry["position"] for entry in payload["entries"]],
            [1, 2],
        )
        self.assertEqual(payload["entries"][1]["replyTo"], 1)

        status, output, _ = self.run_cli(
            "ack",
            stream_id,
            "--reader",
            "b",
            "--through",
            "2",
        )
        self.assertEqual(status, 0)
        self.assertIn("through=2", output)

        _, output, _ = self.run_cli(
            "list",
            stream_id,
            "--reader",
            "b",
        )
        self.assertEqual(output, "")

    def test_current_thread_is_the_default_author_and_reader(self):
        _, stream_id, _ = self.run_cli("create")
        stream_id = stream_id.strip()

        status, _, _ = self.run_cli(
            "append",
            stream_id,
            "hello",
            env={"CODEX_THREAD_ID": "self"},
        )
        self.assertEqual(status, 0)

        _, output, _ = self.run_cli(
            "list",
            stream_id,
            "--json",
            env={"CODEX_THREAD_ID": "self"},
        )
        payload = json.loads(output)
        self.assertEqual(payload["reader"], "self")
        self.assertEqual(payload["entries"][0]["author"], "self")

        status, _, _ = self.run_cli(
            "ack",
            stream_id,
            "--through",
            "1",
            env={"CODEX_THREAD_ID": "self"},
        )
        self.assertEqual(status, 0)

        _, output, _ = self.run_cli(
            "list",
            stream_id,
            "--json",
            env={"CODEX_THREAD_ID": "self"},
        )
        self.assertEqual(json.loads(output)["entries"], [])

    def test_explicit_reader_overrides_current_thread(self):
        _, stream_id, _ = self.run_cli("create")
        stream_id = stream_id.strip()
        self.run_cli("append", stream_id, "--author", "a", "first")

        _, output, _ = self.run_cli(
            "list",
            stream_id,
            "--reader",
            "other",
            "--json",
            env={"CODEX_THREAD_ID": "self"},
        )
        self.assertEqual(json.loads(output)["reader"], "other")

    def test_explicit_after_does_not_infer_a_reader(self):
        _, stream_id, _ = self.run_cli("create")
        stream_id = stream_id.strip()
        self.run_cli("append", stream_id, "--author", "a", "first")

        _, output, _ = self.run_cli(
            "list",
            stream_id,
            "--after",
            "0",
            "--json",
            env={"CODEX_THREAD_ID": "self"},
        )
        payload = json.loads(output)
        self.assertIsNone(payload["reader"])
        self.assertIsNone(payload["ackThrough"])
        self.assertEqual([entry["position"] for entry in payload["entries"]], [1])

    def test_list_without_current_identity_starts_from_the_beginning(self):
        _, stream_id, _ = self.run_cli("create")
        stream_id = stream_id.strip()
        self.run_cli("append", stream_id, "--author", "a", "first")

        _, output, _ = self.run_cli("list", stream_id, "--json")
        payload = json.loads(output)
        self.assertIsNone(payload["reader"])
        self.assertEqual([entry["position"] for entry in payload["entries"]], [1])

    def test_missing_identity_and_stream_fail_cleanly(self):
        status, _, error = self.run_cli("append", "missing", "hello")
        self.assertEqual(status, 1)
        self.assertIn("--author is required", error)

        status, _, error = self.run_cli(
            "list",
            "missing",
            "--reader",
            "reader",
        )
        self.assertEqual(status, 1)
        self.assertIn("stream not found", error)

        status, _, error = self.run_cli(
            "ack",
            "missing",
            "--through",
            "0",
        )
        self.assertEqual(status, 1)
        self.assertIn("--reader is required", error)
