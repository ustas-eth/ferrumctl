from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, replace
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
    session_meta_thread_id: str | None = None
    line_number: int | None = None
    checkpoint_index: int | None = None
    window_number: int | None = None
    window_id: str | None = None
    replacement_history: tuple[dict[str, Any], ...] | None = None
    visible: bool = False

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
            "sessionMetaThreadId": distinct_session_meta_thread_id(
                self.thread_id,
                self.session_meta_thread_id,
            ),
            "checkpointIndex": self.checkpoint_index,
            "windowNumber": self.window_number,
            "windowId": self.window_id,
            "retainedItems": self.retained_items,
            "visible": self.visible,
        }


@dataclass(frozen=True)
class TranscriptMessage:
    line_number: int
    timestamp: str | None
    role: str
    turn_id: str | None
    text: str


@dataclass(frozen=True)
class RolloutMemory:
    thread_id: str
    path: Path
    states: tuple[MemoryState, ...]
    visible_memory_ids: frozenset[str] = frozenset()
    session_meta_thread_id: str | None = None
    messages: tuple[TranscriptMessage, ...] = ()
    compaction_count: int = 0
    last_compaction_line: int | None = None


def distinct_session_meta_thread_id(
    thread_id: str,
    session_meta_thread_id: str | None,
) -> str | None:
    if session_meta_thread_id == thread_id:
        return None
    return session_meta_thread_id


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
    item_id = item.get("id")
    if not isinstance(item_id, str) or not item_id:
        raise MemoryctlError("compaction item has no stable response-item id")
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
        and isinstance(value.get("id"), str)
        and bool(value["id"])
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


def _message_text(payload: dict[str, Any]) -> str:
    content = payload.get("content")
    if not isinstance(content, list):
        return ""
    parts = [
        item.get("text")
        for item in content
        if isinstance(item, dict) and isinstance(item.get("text"), str)
    ]
    return "\n".join(part for part in parts if part)


def scan_rollout(path: Path, *, include_messages: bool = False) -> RolloutMemory:
    path_thread_id = thread_id_from_path(path)
    reported_thread_id = path_thread_id or path.stem
    session_meta_thread_id: str | None = None
    model: str | None = None
    model_provider: str | None = None
    states: list[MemoryState] = []
    visible_memory_ids: set[str] = set()
    visible_state_indices: set[int] = set()
    messages: list[TranscriptMessage] = []
    checkpoint_index = 0
    last_compaction_line: int | None = None

    try:
        with path.open("r", encoding="utf-8", errors="strict") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not any(marker in line for marker in INTERESTING_MARKERS) and not (
                    include_messages and '"response_item"' in line
                ):
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
                    session_meta_thread_id = (
                        _string(payload.get("id")) or session_meta_thread_id
                    )
                    if path_thread_id is None and session_meta_thread_id is not None:
                        reported_thread_id = session_meta_thread_id
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
                if (
                    include_messages
                    and record_type == "response_item"
                    and payload.get("type") == "message"
                    and payload.get("role") in {"user", "assistant"}
                ):
                    text = _message_text(payload)
                    if text:
                        metadata = payload.get(
                            "internal_chat_message_metadata_passthrough"
                        )
                        turn_id = (
                            _string(metadata.get("turn_id"))
                            if isinstance(metadata, dict)
                            else None
                        )
                        messages.append(
                            TranscriptMessage(
                                line_number=line_number,
                                timestamp=_string(record.get("timestamp")),
                                role=str(payload["role"]),
                                turn_id=turn_id,
                                text=text,
                            )
                        )
                    continue
                if record_type == "compacted":
                    checkpoint_index += 1
                    last_compaction_line = line_number
                    replacement = payload.get("replacement_history")
                    items = _memory_items(replacement)
                    visible_memory_ids = {
                        memory_id(item)[0] for item in items
                    }
                    visible_state_indices.clear()
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
                            session_meta_thread_id=session_meta_thread_id,
                            line_number=line_number,
                            checkpoint_index=checkpoint_index,
                            window_number=window_number,
                            window_id=_string(payload.get("window_id")),
                            replacement_history=tuple(replacement),
                        )
                    )
                    visible_state_indices.add(len(states) - 1)
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
                            session_meta_thread_id=session_meta_thread_id,
                            line_number=line_number,
                        )
                    )
                    visible_state_indices.add(len(states) - 1)
    except UnicodeDecodeError as exc:
        raise MemoryctlError(f"rollout is not valid UTF-8: {path}") from exc
    except OSError as exc:
        raise MemoryctlError(f"failed to read rollout {path}: {exc}") from exc

    visible_states = tuple(
        replace(state, visible=index in visible_state_indices)
        for index, state in enumerate(states)
    )
    return RolloutMemory(
        reported_thread_id,
        path,
        visible_states,
        frozenset(visible_memory_ids),
        session_meta_thread_id,
        tuple(messages),
        checkpoint_index,
        last_compaction_line,
    )


def load_rollout(
    codex_home: Path,
    source: str,
    *,
    include_messages: bool = False,
) -> RolloutMemory:
    return scan_rollout(
        find_rollout(codex_home, source),
        include_messages=include_messages,
    )
