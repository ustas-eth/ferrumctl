from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .constants import EXPORT_KIND, EXPORT_SCHEMA_VERSION
from .errors import MemoryctlError
from .rollouts import MemoryState, is_memory_item, memory_id


def build_envelope(state: MemoryState, *, full_checkpoint: bool) -> dict[str, Any]:
    if full_checkpoint:
        if state.replacement_history is None:
            raise MemoryctlError("full export requires a generated checkpoint")
        items = list(state.replacement_history)
        scope = "checkpoint"
    else:
        items = [state.memory_item]
        scope = "memory"
    return {
        "schemaVersion": EXPORT_SCHEMA_VERSION,
        "kind": EXPORT_KIND,
        "scope": scope,
        "source": {
            "threadId": state.thread_id,
            "observedAt": state.observed_at,
            "checkpointIndex": state.checkpoint_index,
            "windowNumber": state.window_number,
            "windowId": state.window_id,
            "model": state.model,
            "modelProvider": state.model_provider,
        },
        "memory": {
            "id": state.memory_id,
            "payloadBytes": state.payload_bytes,
        },
        "items": items,
    }


def validate_envelope(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MemoryctlError("memory export must be a JSON object")
    if value.get("schemaVersion") != EXPORT_SCHEMA_VERSION:
        raise MemoryctlError("unsupported memory export schema version")
    if value.get("kind") != EXPORT_KIND:
        raise MemoryctlError("file is not a codex-memoryctl export")
    if not isinstance(value.get("source"), dict):
        raise MemoryctlError("memory export has invalid source metadata")
    scope = value.get("scope")
    if scope not in {"memory", "checkpoint"}:
        raise MemoryctlError("memory export has an invalid scope")
    items = value.get("items")
    if not isinstance(items, list) or not items or not all(
        isinstance(item, dict) for item in items
    ):
        raise MemoryctlError("memory export has invalid items")
    memories = [item for item in items if is_memory_item(item)]
    if len(memories) != 1:
        raise MemoryctlError("memory export must contain exactly one compaction item")
    digest, size = memory_id(memories[0])
    memory = value.get("memory")
    if not isinstance(memory, dict) or memory.get("id") != digest:
        raise MemoryctlError("memory export digest does not match its compaction item")
    if memory.get("payloadBytes") != size:
        raise MemoryctlError("memory export size does not match its compaction item")
    if scope == "memory" and len(items) != 1:
        raise MemoryctlError("memory-only export contains additional items")
    return value


def read_envelope(path: str) -> dict[str, Any]:
    try:
        if path == "-":
            import sys

            value = json.load(sys.stdin)
        else:
            with Path(path).expanduser().open("r", encoding="utf-8") as handle:
                value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise MemoryctlError(f"failed to read memory export {path}: {exc}") from exc
    return validate_envelope(value)


def write_envelope(
    envelope: dict[str, Any],
    path: str,
    *,
    force: bool,
) -> None:
    rendered = json.dumps(envelope, indent=2) + "\n"
    if path == "-":
        import sys

        sys.stdout.write(rendered)
        return

    destination = Path(path).expanduser()
    flags = os.O_WRONLY | os.O_CREAT
    flags |= os.O_TRUNC if force else os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(destination, flags, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                descriptor = -1
                handle.write(rendered)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    except FileExistsError as exc:
        raise MemoryctlError(
            f"output already exists: {destination}; pass --force to replace it"
        ) from exc
    except OSError as exc:
        raise MemoryctlError(f"failed to write memory export {destination}: {exc}") from exc
