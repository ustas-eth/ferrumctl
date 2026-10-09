#!/usr/bin/env python3
"""Clear known legacy ferrumctl agent-message IDs in cold local rollouts.

Each replacement occupies exactly the original number of bytes. Paginated
history offsets and shared-prefix references therefore remain valid.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import uuid


LEGACY_ID = re.compile(r"amsg_(?:memoryctl_)?[0-9a-f]{32}\Z")
LEGACY_BYTES = re.compile(rb'"amsg_(?:memoryctl_)?[0-9a-f]{32}"')
TOKENS = re.compile(rb'"(?:[^"\\]|\\.)*"|[{}\[\]:,]')


def clear_legacy_ids(value):
    """Only IDs on agent-message objects qualify; text and provenance stay intact."""
    count = 0
    pending = [value]
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            item_id = node.get("id")
            if (
                node.get("type") == "agent_message"
                and isinstance(item_id, str)
                and LEGACY_ID.fullmatch(item_id)
            ):
                node["id"] = None
                count += 1
            pending.extend(node.values())
        elif isinstance(node, list):
            pending.extend(node)
    return count


def repair_line(line: bytes) -> tuple[bytes, int]:
    if not LEGACY_BYTES.search(line):
        return line, 0
    expected = json.loads(line)
    count = clear_legacy_ids(expected)
    if not count:
        return line, 0
    # Locate actual object fields without reserializing other JSON or changing
    # Unicode encoding, formatting, ciphertext, line lengths, or byte offsets.
    stack = []
    spans = []
    for match in TOKENS.finditer(line):
        token = match.group()
        if token in (b"{", b"["):
            stack.append({"kind": token, "key": None, "key_next": True, "type": None, "id": None})
        elif token in (b"}", b"]"):
            node = stack.pop()
            if node["kind"] == b"{" and node["type"] == "agent_message" and node["id"]:
                spans.append(node["id"])
        elif stack and stack[-1]["kind"] == b"{":
            node = stack[-1]
            if token == b",":
                node["key_next"] = True
                node["key"] = None
            elif token.startswith(b'"'):
                value = json.loads(token)
                if node["key_next"]:
                    node["key"] = value
                    node["key_next"] = False
                else:
                    if node["key"] == "type":
                        node["type"] = value
                    elif node["key"] == "id" and LEGACY_ID.fullmatch(value):
                        node["id"] = match.span()
                    node["key"] = None
    if len(spans) != count:
        raise ValueError("could not locate all eligible ID fields safely")
    patched = bytearray(line)
    for start, end in spans:
        patched[start:end] = b"null" + b" " * (end - start - 4)
    repaired = bytes(patched)
    if len(repaired) != len(line) or json.loads(repaired) != expected:
        raise ValueError("repair changed fields other than eligible IDs")
    return repaired, count


@contextlib.contextmanager
def writer_lock(home: Path, thread_id: str):
    # Codex File::lock uses flock on Linux. Coordination prevents a lock-file
    # cleanup from racing acquisition; the thread lock is held through publication.
    import fcntl

    directory = home / "thread-writer-locks"
    directory.mkdir(exist_ok=True)
    with (directory / ".coordination.lock").open("a+b") as coordination:
        fcntl.flock(coordination, fcntl.LOCK_EX)
        lock = (directory / f"{thread_id}.lock").open("a+b")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            lock.close()
            raise
    try:
        yield
    finally:
        lock.close()


def identity(path: Path):
    value = path.stat()
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


def inspect_file(path: Path, selected: set[str] | None = None) -> dict | None:
    with path.open("rb") as source:
        metadata = json.loads(source.readline())["payload"]
        thread_id = str(uuid.UUID(metadata["id"]))
        if selected and thread_id not in selected:
            return None
        count = 0
        for line in source:
            _, changed = repair_line(line)
            count += changed
    return {"threadId": thread_id, "path": str(path), "idOccurrences": count}


def apply_file(home: Path, path: Path, report: dict, backup_root: Path):
    with writer_lock(home, report["threadId"]):
        original_identity = identity(path)
        relative = path.relative_to(home)
        backup = backup_root / relative
        backup.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive backup creation prevents a rerun from overwriting recovery data.
        with path.open("rb") as source, backup.open("xb") as destination:
            shutil.copyfileobj(source, destination)
            destination.flush()
            os.fsync(destination.fileno())
        shutil.copystat(path, backup)
        stage_name = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".id-repair-", delete=False) as stage:
                stage_name = stage.name
                digest = hashlib.sha256()
                count = 0
                with backup.open("rb") as source:
                    for line in source:
                        digest.update(line)
                        repaired, changed = repair_line(line)
                        stage.write(repaired)
                        count += changed
                stage.flush()
                os.fsync(stage.fileno())
            if count != report["idOccurrences"] or identity(path) != original_identity:
                raise ValueError("rollout changed after inspection; nothing published")
            shutil.copystat(path, stage_name)
            if Path(stage_name).stat().st_size != original_identity[2]:
                raise ValueError("repair changed rollout byte length")
            os.replace(stage_name, path)
            stage_name = None
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            report.update(status="repaired", backup=str(backup), originalSha256=digest.hexdigest())
        finally:
            if stage_name is not None:
                Path(stage_name).unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", type=Path, default=Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser())
    parser.add_argument("--thread", action="append", default=[], help="restrict to these thread IDs (repeatable)")
    parser.add_argument("--apply", action="store_true", help="repair cold files; otherwise scan only")
    parser.add_argument("--backup-dir", type=Path, help="new, private backup directory; required with --apply")
    args = parser.parse_args(argv)
    if args.apply and args.backup_dir is None:
        parser.error("--apply requires --backup-dir")
    if args.apply and not sys.platform.startswith("linux"):
        parser.error("live-writer protection is verified on Linux only")
    home = args.codex_home.resolve(strict=True)
    selected = {str(uuid.UUID(value)) for value in args.thread}
    backup_root = None
    if args.apply:
        backup_root = args.backup_dir.resolve()
        if backup_root == home or any(backup_root.is_relative_to(home / root) for root in ("sessions", "archived_sessions")):
            parser.error("backup directory must be outside the rollout roots")
        backup_root.mkdir(mode=0o700, parents=True, exist_ok=False)
    reports = []
    errors = []
    compressed = []
    for root in ("sessions", "archived_sessions"):
        directory = home / root
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("rollout-*")):
            if path.is_symlink() or not path.is_file():
                continue
            if path.name.endswith(".jsonl.zst"):
                if not selected or any(value in path.name for value in selected):
                    compressed.append(str(path))
                continue
            if not path.name.endswith(".jsonl"):
                continue
            try:
                report = inspect_file(path, selected)
                if report is None:
                    continue
                if not report["idOccurrences"]:
                    continue
                report["status"] = "affected"
                if args.apply:
                    try:
                        apply_file(home, path, report, backup_root)
                    except BlockingIOError:
                        report["status"] = "busy"
                reports.append(report)
            except (OSError, ValueError, KeyError) as exc:
                errors.append({"path": str(path), "error": str(exc)})
    result = {
        "mode": "apply" if args.apply else "scan",
        "affectedFiles": len(reports),
        "repairedFiles": sum(item["status"] == "repaired" for item in reports),
        "busyFiles": sum(item["status"] == "busy" for item in reports),
        "files": reports, "compressedFilesNotInspected": compressed, "errors": errors,
    }
    if backup_root is not None:
        (backup_root / "manifest.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 1 if errors or compressed or result["busyFiles"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
