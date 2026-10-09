from __future__ import annotations

import contextlib
import fcntl
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest


spec = importlib.util.spec_from_file_location(
    "repair_ids", Path(__file__).parents[1] / "scripts/repair-response-item-ids.py"
)
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)

THREAD = "11111111-1111-4111-8111-111111111111"
OLD = "amsg_memoryctl_0123456789abcdef0123456789abcdef"


def agent(item_id=OLD):
    return {"type": "agent_message", "id": item_id, "author": "memoryctl",
            "recipient": THREAD, "content": [{"type": "input_text", "text": "Café: retain me"}]}


def line(value):
    return (json.dumps(value, ensure_ascii=False) + "\n").encode()


class RepairIdsTests(unittest.TestCase):
    def test_only_known_agent_ids_change_and_byte_offsets_stay_identical(self):
        original = line({"type": "compacted", "payload": {"replacement_history": [
            agent(), agent("amsg_0123456789abcdef0123456789abcdef"),
            agent("amsg_11111111-1111-4111-8111-111111111111"),
            agent("amsg_wake_0123456789ab_1"),
            {"type": "compaction", "id": "cmp_provider", "encrypted_content": OLD},
            {"type": "message", "id": OLD, "role": "user", "content": [{"type": "input_text", "text": OLD}]},
            {"provenance": {"id": OLD}},
        ]}})
        patched, count = repair.repair_line(original)
        self.assertEqual(count, 2)
        self.assertEqual(len(patched), len(original))
        expected = json.loads(original)
        repair.clear_legacy_ids(expected)
        self.assertEqual(json.loads(patched), expected)
        self.assertEqual(repair.repair_line(patched), (patched, 0))

    def test_fields_can_be_reordered_and_envelopes_nested(self):
        original = line({"payload": {"replacement_history": [{"item": {
            "id": OLD, "recipient": THREAD, "type": "agent_message", "author": "memoryctl",
            "content": [{"text": 'a quoted "id" field and {nested} punctuation'}],
        }}]}})
        patched, count = repair.repair_line(original)
        self.assertEqual(count, 1)
        self.assertIsNone(json.loads(patched)["payload"]["replacement_history"][0]["item"]["id"])
        self.assertEqual(len(patched), len(original))

    def test_bad_json_fails_closed(self):
        with self.assertRaises(ValueError):
            repair.repair_line(b'{"id": "' + OLD.encode() + b'", broken}')

    def home(self, root):
        home = root / "codex"
        sessions = home / "sessions" / "2026" / "01" / "01"
        sessions.mkdir(parents=True)
        path = sessions / f"rollout-synthetic-{THREAD}.jsonl"
        data = line({"type": "session_meta", "payload": {"id": THREAD}})
        data += line({"type": "response_item", "payload": agent()})
        data += line({"type": "compacted", "payload": {"replacement_history": [agent()]}})
        path.write_bytes(data)
        return home, path, data

    def run_tool(self, arguments):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = repair.main(arguments)
        return code, json.loads(output.getvalue())

    def test_scan_then_apply_preserves_backups_and_line_offsets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home, path, data = self.home(root)
            code, report = self.run_tool(["--codex-home", str(home)])
            self.assertEqual(code, 0)
            self.assertEqual(report["affectedFiles"], 1)
            self.assertEqual(path.read_bytes(), data)
            self.assertFalse((home / "thread-writer-locks").exists())
            backup = root / "backups"
            code, report = self.run_tool(["--codex-home", str(home), "--apply", "--backup-dir", str(backup)])
            self.assertEqual(code, 0)
            self.assertEqual(report["repairedFiles"], 1)
            self.assertEqual(Path(report["files"][0]["backup"]).read_bytes(), data)
            self.assertEqual([len(row) for row in path.read_bytes().splitlines()], [len(row) for row in data.splitlines()])
            self.assertEqual((backup.stat().st_mode & 0o777), 0o700)
            self.assertEqual(self.run_tool(["--codex-home", str(home)])[1]["affectedFiles"], 0)

    def test_busy_writer_is_not_touched(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home, path, data = self.home(root)
            directory = home / "thread-writer-locks"
            directory.mkdir()
            with (directory / f"{THREAD}.lock").open("a+b") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                code, report = self.run_tool(["--codex-home", str(home), "--apply", "--backup-dir", str(root / "backups")])
            self.assertEqual(code, 1)
            self.assertEqual(report["busyFiles"], 1)
            self.assertEqual(path.read_bytes(), data)

    def test_compressed_and_corrupt_files_are_reported_not_silently_skipped(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home, path, _ = self.home(root)
            path.with_suffix(".jsonl.zst").write_bytes(b"compressed fixture")
            path.write_bytes(b"not json\n")
            code, report = self.run_tool(["--codex-home", str(home)])
            self.assertEqual(code, 1)
            self.assertEqual(len(report["errors"]), 1)
            self.assertEqual(len(report["compressedFilesNotInspected"]), 1)

    def test_selection_and_backup_reuse_are_safe(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home, path, data = self.home(root)
            other = "22222222-2222-4222-8222-222222222222"
            code, report = self.run_tool(["--codex-home", str(home), "--thread", other])
            self.assertEqual(code, 0)
            self.assertEqual(report["affectedFiles"], 0)
            backup = root / "backups"
            backup.mkdir()
            with self.assertRaises(FileExistsError):
                self.run_tool(["--codex-home", str(home), "--apply", "--backup-dir", str(backup)])
            self.assertEqual(path.read_bytes(), data)


if __name__ == "__main__":
    unittest.main()
