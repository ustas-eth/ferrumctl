import importlib.util
import json
import os
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "examples/restricted-operations/adapter.py"
SPEC = importlib.util.spec_from_file_location("operation_adapter", ADAPTER)
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.log = self.directory / "calls.jsonl"
        self.binary = self.directory / "backend"
        self.binary.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "record = {'argv': sys.argv[1:], 'stdin': sys.stdin.read()}\n"
            "with Path(os.environ['ADAPTER_TEST_LOG']).open('a') as log:\n"
            "    log.write(json.dumps(record) + '\\n')\n"
            "print(os.environ['ADAPTER_TEST_RESULT'])\n"
            "print('private backend diagnostics', file=sys.stderr)\n"
            "raise SystemExit(int(os.environ.get('ADAPTER_TEST_STATUS', '0')))\n"
        )
        self.binary.chmod(0o700)
        self.env = {**os.environ, "ADAPTER_TEST_LOG": str(self.log)}
        self.set_result({"outcome": "accepted", "messageOutcome": "accepted",
                         "itemId": "amsg_test", "private": "hidden"})

    def set_result(self, result, status=0):
        self.env["ADAPTER_TEST_RESULT"] = json.dumps(result)
        self.env["ADAPTER_TEST_STATUS"] = str(status)

    def arguments(self, operation="report", binary=None, extra=()):
        argv = [sys.executable, str(ADAPTER), operation, "--bin", str(binary or self.binary)]
        if operation != "append":
            argv += ["--to", "fixed-thread", "--endpoint", f"unix://{self.directory}/upstream.sock"]
        if operation != "report":
            argv += ["--state", str(self.directory / "state.sqlite3")]
        if operation != "self-wake":
            argv += ["--from", "fixed-worker"]
        if operation == "append":
            argv += ["--stream", "fixed-stream"]
        return [*argv, *extra]

    def run_adapter(self, request, operation="report", *, raw=False, binary=None, extra=()):
        payload = request if raw else (json.dumps(request) + "\n").encode()
        proc = subprocess.run(self.arguments(operation, binary, extra), input=payload,
                              capture_output=True, env=self.env, timeout=5)
        return proc, json.loads(proc.stdout)

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def source_binary(self, module):
        path = self.directory / module
        path.write_text(f"#!/bin/sh\nexec {shlex.quote(sys.executable)} -m {module}.cli \"$@\"\n")
        path.chmod(0o700)
        sources = [ROOT / "packages" / package / "src"
                   for package in ("streamctl", "codex-wakectl", "codex-threadctl")]
        self.env["PYTHONPATH"] = os.pathsep.join(map(str, sources))
        return path

    def test_reporting_fixes_author_target_and_role_and_returns_only_receipt(self):
        text = 'Report\n--to another $(touch forbidden) "quoted"'
        proc, public = self.run_adapter({"text": text})
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(public, {"outcome": "accepted", "itemId": "amsg_test"})
        call = self.calls()[0]
        self.assertEqual(call["stdin"], text)
        self.assertEqual(call["argv"][:6], ["send", "fixed-thread", "--from", "fixed-worker", "--stdin", "--endpoint"])
        self.assertNotIn("--wake", call["argv"])
        self.assertEqual(proc.stderr, b"")

    def test_waking_and_fixed_signal_are_operator_choices(self):
        self.set_result({"outcome": "partial", "messageOutcome": "accepted", "itemId": "amsg_test",
                         "wake": {"outcome": "uncertain", "reason": "private"}}, status=1)
        proc, public = self.run_adapter({}, extra=("--signal", "Update available.", "--wake"))
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(public, {"outcome": "partial", "itemId": "amsg_test", "wakeOutcome": "uncertain"})
        self.assertEqual(self.calls()[0]["stdin"], "Update available.")
        self.assertIn("--wake", self.calls()[0]["argv"])
        self.assertEqual(len(self.calls()), 1)
        proc, public = self.run_adapter({"text": "replace signal"}, extra=("--signal", "Fixed."))
        self.assertEqual(public["outcome"], "rejected")
        self.assertEqual(len(self.calls()), 1)

    def test_invalid_requests_never_reach_the_backend(self):
        requests = [b'{"text":"ok","to":"other"}\n', b'{"text":"ok","args":[]}\n',
                    b'{"text":"ok","text":"other"}\n', b'{"text":[]}\n',
                    b'{"text":" "}\n', b'[]\n', b'{"text":"ok"}', b'\xff\n',
                    b'{"text":"\\ud800"}\n',
                    b'{"text":' + b'[' * 1100 + b'0' + b']' * 1100 + b'}\n',
                    b'x' * (adapter.MAX_REQUEST_BYTES + 1) + b'\n']
        for request in requests:
            with self.subTest(request=request[:80]):
                proc, public = self.run_adapter(request, raw=True)
                self.assertNotEqual(proc.returncode, 0)
                self.assertEqual(public, {"outcome": "rejected", "code": "invalidRequest"})
        self.assertEqual(self.calls(), [])

    def test_unknown_wake_result_does_not_hide_accepted_message(self):
        for wake in (None, {"outcome": "unrecognized private details"}, {"outcome": {"invalid": True}}):
            with self.subTest(wake=wake):
                self.set_result({"outcome": "partial", "messageOutcome": "accepted",
                                 "itemId": "amsg_test", "wake": wake}, status=1)
                proc, public = self.run_adapter({"text": "Report"}, extra=("--wake",))
                self.assertNotEqual(proc.returncode, 0)
                self.assertEqual(public, {"outcome": "partial", "itemId": "amsg_test", "wakeOutcome": "uncertain"})

    def test_delays_are_bounded_and_cannot_supply_predicates_or_input(self):
        for request in ({"afterSeconds": True}, {"afterSeconds": 0}, {"afterSeconds": 86401},
                        {"afterSeconds": 1.5}, {"afterSeconds": 1, "cmd": "anything"},
                        {"afterSeconds": 1, "input": "user instructions"}):
            with self.subTest(request=request):
                _, public = self.run_adapter(request, "self-wake")
                self.assertEqual(public["outcome"], "rejected")
        self.assertEqual(self.calls(), [])

    def test_uncertain_message_preserves_its_id_without_forwarding_errors_or_retrying(self):
        self.set_result({"error": {"outcome": "uncertain", "itemId": "amsg_uncertain",
                                   "message": "private source path"}}, status=1)
        proc, public = self.run_adapter({"text": "Report"})
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(public, {"outcome": "uncertain", "code": "backendFailure", "itemId": "amsg_uncertain"})
        self.assertEqual(len(self.calls()), 1)
        self.assertEqual(proc.stderr, b"")

    def test_known_non_submission_is_not_reported_as_uncertain(self):
        for outcome, code in (("rejected", "directInputUnsupported"),
                              ("notSubmitted", "threadNotLoaded")):
            with self.subTest(outcome=outcome):
                self.set_result({"error": {"outcome": outcome, "code": code,
                                           "message": "private backend details"}}, status=1)
                before = len(self.calls())
                proc, public = self.run_adapter({"text": "Report"})
                self.assertNotEqual(proc.returncode, 0)
                self.assertEqual(public, {"outcome": outcome, "code": "backendFailure"})
                self.assertEqual(len(self.calls()), before + 1)
                self.assertEqual(proc.stderr, b"")

    def test_accepted_message_keeps_known_wake_non_submission(self):
        self.set_result({"outcome": "partial", "messageOutcome": "accepted",
                         "itemId": "amsg_test", "wake": {"outcome": "notSubmitted",
                         "code": "threadNotLoaded", "message": "private backend details"}}, status=1)
        proc, public = self.run_adapter({"text": "Report"}, extra=("--wake",))
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(public, {"outcome": "partial", "itemId": "amsg_test",
                                  "wakeOutcome": "notSubmitted"})
        self.assertEqual(len(self.calls()), 1)

    def test_timeout_and_invalid_response_are_uncertain_not_retried(self):
        args = adapter.build_parser().parse_args(self.arguments()[2:])
        for failure in (subprocess.TimeoutExpired("backend", 60), UnicodeError("bad stdout")):
            with (
                mock.patch.object(adapter, "build_parser", return_value=mock.Mock(parse_args=lambda: args)),
                mock.patch.object(adapter, "read_request", return_value={"text": "Report"}),
                mock.patch.object(adapter.subprocess, "run", side_effect=failure) as run,
                mock.patch("builtins.print") as output,
            ):
                self.assertEqual(adapter.main(), 1)
                self.assertEqual(json.loads(output.call_args.args[0])["outcome"], "uncertain")
                run.assert_called_once()
        self.env["ADAPTER_TEST_RESULT"] = "not JSON: private details"
        _, public = self.run_adapter({"text": "Report"})
        self.assertEqual(public, {"outcome": "uncertain", "code": "backendFailure"})

    def test_append_against_real_cli_does_not_expose_other_entries(self):
        binary = self.source_binary("streamctl")
        path = self.directory / "state.sqlite3"
        created = subprocess.run([str(binary), "create", "--state", str(path)],
                                 capture_output=True, text=True, env=self.env, check=True).stdout.strip()
        subprocess.run([str(binary), "append", created, "--author", "other", "private existing entry",
                        "--state", str(path)], capture_output=True, env=self.env, check=True)
        argv = self.arguments("append", binary)
        argv[argv.index("--stream") + 1] = created
        text = 'A finding\n$(touch forbidden)'
        proc = subprocess.run(argv, input=(json.dumps({"text": text}) + "\n").encode(),
                              capture_output=True, env=self.env, timeout=5)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), {"outcome": "committed", "position": 2})
        result = subprocess.run([str(binary), "list", created, "--after", "0", "--state", str(path), "--json"],
                                capture_output=True, text=True, env=self.env, check=True)
        entries = json.loads(result.stdout)["entries"]
        self.assertEqual(entries[1]["text"], text)
        self.assertEqual(entries[1]["author"], "fixed-worker")

    def test_self_wake_persists_only_a_fixed_target_time_job(self):
        binary = self.source_binary("codex_wakectl")
        proc, public = self.run_adapter({"afterSeconds": 120}, "self-wake", binary=binary)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(set(public), {"outcome", "jobId"})
        self.assertEqual(public["outcome"], "scheduled")
        result = subprocess.run([str(binary), "list", "--state", str(self.directory / "state.sqlite3"), "--json"],
                                capture_output=True, text=True, env=self.env, check=True)
        job = json.loads(result.stdout)["jobs"][0]
        self.assertEqual(job["targetThreadId"], "fixed-thread")
        self.assertEqual(job["condition"]["type"], "time")
        self.assertEqual(job["action"], {"type": "event"})
        self.assertFalse((self.directory / "upstream.sock").exists())

    @unittest.skipUnless(shutil.which("socat"), "socat is optional example transport")
    def test_documented_socket_transport_accepts_one_report_and_rejects_extra_rights(self):
        wrapper = self.directory / "report.sh"
        wrapper.write_text("#!/bin/sh\nexec " + shlex.join(self.arguments()) + "\n")
        wrapper.chmod(0o700)
        sock = self.directory / "report.sock"
        proc = subprocess.Popen([shutil.which("socat"), "-T", "65",
                                 f"UNIX-LISTEN:{sock},mode=0600,fork,max-children=8",
                                 f"EXEC:{wrapper}"], env=self.env, stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, start_new_session=True, umask=0o077)
        try:
            deadline = time.monotonic() + 3
            while not sock.exists() and proc.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(sock.exists())
            self.assertEqual(sock.stat().st_mode & 0o777, 0o600)
            duplicate = subprocess.run([shutil.which("socat"), f"UNIX-LISTEN:{sock}", "PIPE"],
                                       capture_output=True, timeout=3)
            self.assertNotEqual(duplicate.returncode, 0)
            self.assertTrue(sock.exists())
            for request, outcome in (({"text": "Report"}, "accepted"),
                                     ({"text": "Report", "read": True}, "rejected")):
                with socket.socket(socket.AF_UNIX) as client:
                    client.settimeout(3)
                    client.connect(str(sock))
                    client.sendall((json.dumps(request) + "\n").encode())
                    with client.makefile("rb") as response:
                        self.assertEqual(json.loads(response.readline())["outcome"], outcome)
            self.assertEqual(len(self.calls()), 1)
        finally:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            proc.communicate(timeout=3)


if __name__ == "__main__":
    unittest.main()
