from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .constants import MEMORY_ITEM_TYPES, MEMORY_REF_HEX_LENGTH
from .errors import MemoryctlError

THREAD_ID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
INTERESTING_MARKERS = (
    '"session_meta"',
    '"turn_context"',
    '"thread_settings_applied"',
    '"compacted"',
    '"compaction"',
)


@dataclass(frozen=True)
class MemoryState:
    thread_id: str
    rollout_path: Path
    origin: str
    observed_at: str | None
    memory_item: dict[str, Any]
    memory_id: str
    payload_bytes: int
    model: str | None
    model_provider: str | None
    checkpoint_index: int | None = None
    window_number: int | None = None
    window_id: str | None = None
    replacement_history: tuple[dict[str, Any], ...] | None = None

    @property
    def retained_items(self) -> int | None:
        if self.replacement_history is None:
            return None
        return len(self.replacement_history) - 1

    def metadata(self) -> dict[str, Any]:
        return {
            "threadId": self.thread_id,
            "origin": self.origin,
            "observedAt": self.observed_at,
            "memoryId": memory_ref(self.memory_id),
            "payloadBytes": self.payload_bytes,
            "model": self.model,
            "modelProvider": self.model_provider,
            "checkpointIndex": self.checkpoint_index,
            "windowNumber": self.window_number,
            "windowId": self.window_id,
            "retainedItems": self.retained_items,
        }


@dataclass(frozen=True)
class RolloutMemory:
    thread_id: str
    path: Path
    states: tuple[MemoryState, ...]
    visible_memory_ids: frozenset[str] = frozenset()


def resolve_codex_home(value: str | None) -> Path:
    if value:
        path = Path(value).expanduser()
    elif os.environ.get("CODEX_HOME"):
        path = Path(os.environ["CODEX_HOME"]).expanduser()
    else:
        path = Path.home() / ".codex"
    if not path.is_dir():
        raise MemoryctlError(f"Codex home is not a directory: {path}")
    return path


def memory_id(item: dict[str, Any]) -> tuple[str, int]:
    encrypted = item.get("encrypted_content")
    if not isinstance(encrypted, str) or not encrypted:
        raise MemoryctlError("compaction item has no encrypted content")
    encoded = encrypted.encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}", len(encoded)


def memory_ref(value: str) -> str:
    digest = value.removeprefix("sha256:")
    return f"m:{digest[:MEMORY_REF_HEX_LENGTH]}"


def is_memory_item(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("type") in MEMORY_ITEM_TYPES
        and isinstance(value.get("encrypted_content"), str)
        and bool(value["encrypted_content"])
    )


def thread_id_from_path(path: Path) -> str | None:
    match = THREAD_ID_RE.search(path.name)
    return match.group(0) if match is not None else None


def find_rollout(codex_home: Path, source: str) -> Path:
    candidate = Path(source).expanduser()
    if candidate.is_file():
        return candidate.resolve()
    if "/" in source and not THREAD_ID_RE.fullmatch(source):
        raise MemoryctlError(f"rollout path is not a file: {candidate}")
    if not THREAD_ID_RE.fullmatch(source):
        raise MemoryctlError(f"invalid Codex thread id: {source}")

    matches: list[Path] = []
    for directory in (codex_home / "sessions", codex_home / "archived_sessions"):
        if not directory.is_dir():
            continue
        try:
            matches.extend(directory.rglob(f"rollout-*{source}.jsonl"))
        except OSError as exc:
            raise MemoryctlError(f"failed to scan {directory}: {exc}") from exc
    unique = sorted({path.resolve() for path in matches if path.is_file()})
    if not unique:
        raise MemoryctlError(f"rollout not found for thread {source}")
    if len(unique) > 1:
        paths = ", ".join(str(path) for path in unique)
        raise MemoryctlError(
            f"multiple rollouts found for thread {source}; use an exact path: {paths}"
        )
    return unique[0]


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _memory_items(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    return [item for item in items if is_memory_item(item)]


def scan_rollout(path: Path) -> RolloutMemory:
    reported_thread_id = thread_id_from_path(path) or path.stem
    model: str | None = None
    model_provider: str | None = None
    states: list[MemoryState] = []
    visible_memory_ids: set[str] = set()
    checkpoint_index = 0

    try:
        with path.open("r", encoding="utf-8", errors="strict") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not any(marker in line for marker in INTERESTING_MARKERS):
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    if not line.endswith("\n"):
                        break
                    raise MemoryctlError(
                        f"invalid rollout JSON at {path}:{line_number}: {exc.msg}"
                    ) from exc
                if not isinstance(record, dict):
                    continue
                record_type = record.get("type")
                payload = record.get("payload")
                if not isinstance(payload, dict):
                    continue

                if record_type == "session_meta":
                    reported_thread_id = (
                        _string(payload.get("id")) or reported_thread_id
                    )
                    model_provider = (
                        _string(payload.get("model_provider")) or model_provider
                    )
                    continue
                if record_type == "turn_context":
                    model = _string(payload.get("model")) or model
                    model_provider = (
                        _string(payload.get("model_provider")) or model_provider
                    )
                    continue
                if (
                    record_type == "event_msg"
                    and payload.get("type") == "thread_settings_applied"
                ):
                    settings = payload.get("thread_settings")
                    if isinstance(settings, dict):
                        model = _string(settings.get("model")) or model
                        model_provider = (
                            _string(settings.get("model_provider")) or model_provider
                        )
                    continue
                if record_type == "compacted":
                    checkpoint_index += 1
                    replacement = payload.get("replacement_history")
                    items = _memory_items(replacement)
                    visible_memory_ids = {
                        memory_id(item)[0] for item in items
                    }
                    if len(items) != 1 or not isinstance(replacement, list):
                        continue
                    if not all(isinstance(item, dict) for item in replacement):
                        continue
                    item = items[0]
                    digest, size = memory_id(item)
                    window_number = payload.get("window_number")
                    if isinstance(window_number, bool) or not isinstance(
                        window_number, int
                    ):
                        window_number = None
                    states.append(
                        MemoryState(
                            thread_id=reported_thread_id,
                            rollout_path=path,
                            origin="checkpoint",
                            observed_at=_string(record.get("timestamp")),
                            memory_item=item,
                            memory_id=digest,
                            payload_bytes=size,
                            model=model,
                            model_provider=model_provider,
                            checkpoint_index=checkpoint_index,
                            window_number=window_number,
                            window_id=_string(payload.get("window_id")),
                            replacement_history=tuple(replacement),
                        )
                    )
                    continue
                if record_type == "response_item" and is_memory_item(payload):
                    digest, size = memory_id(payload)
                    visible_memory_ids.add(digest)
                    states.append(
                        MemoryState(
                            thread_id=reported_thread_id,
                            rollout_path=path,
                            origin="standalone",
                            observed_at=_string(record.get("timestamp")),
                            memory_item=payload,
                            memory_id=digest,
                            payload_bytes=size,
                            model=model,
                            model_provider=model_provider,
                        )
                    )
    except UnicodeDecodeError as exc:
        raise MemoryctlError(f"rollout is not valid UTF-8: {path}") from exc
    except OSError as exc:
        raise MemoryctlError(f"failed to read rollout {path}: {exc}") from exc

    return RolloutMemory(
        reported_thread_id,
        path,
        tuple(states),
        frozenset(visible_memory_ids),
    )


def load_rollout(codex_home: Path, source: str) -> RolloutMemory:
    return scan_rollout(find_rollout(codex_home, source))
