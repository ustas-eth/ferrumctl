from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import MemoryctlError


@dataclass(frozen=True)
class CachedArtifact:
    key: str
    operation: str
    text: str
    model: str
    effort: str
    created_at: str
    elapsed_seconds: float
    attempts: int
    usage: dict[str, Any]
    response_id: str | None


def default_database_path() -> Path:
    root = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return root / "codex-memoryctl" / "derived.sqlite3"


def artifact_key(
    operation: str,
    memory_ids: list[str],
    model: str,
    effort: str,
    instructions: str,
    prompt: str,
) -> str:
    material = json.dumps(
        {
            "operation": operation,
            "memoryIds": memory_ids,
            "model": model,
            "effort": effort,
            "instructions": hashlib.sha256(instructions.encode()).hexdigest(),
            "prompt": hashlib.sha256(prompt.encode()).hexdigest(),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(material.encode()).hexdigest()


def _prepare_database_path(path: Path) -> None:
    default_path = default_database_path().expanduser().resolve()
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path == default_path:
            os.chmod(path.parent, 0o700)
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(descriptor)
        if path == default_path:
            os.chmod(path, 0o600)
    except OSError as exc:
        raise MemoryctlError(
            f"failed to prepare cache database {path}: {exc}"
        ) from exc


def open_database(path: Path) -> sqlite3.Connection:
    path = path.expanduser().resolve()
    _prepare_database_path(path)
    try:
        connection = sqlite3.connect(path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS generated_artifacts (
                key TEXT PRIMARY KEY,
                operation TEXT NOT NULL,
                memory_ids_json TEXT NOT NULL,
                model TEXT NOT NULL,
                effort TEXT NOT NULL,
                instructions_hash TEXT NOT NULL,
                prompt_hash TEXT NOT NULL,
                text TEXT NOT NULL,
                usage_json TEXT NOT NULL,
                response_id TEXT,
                elapsed_seconds REAL NOT NULL,
                attempts INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        return connection
    except (OSError, sqlite3.Error) as exc:
        raise MemoryctlError(f"failed to open cache database {path}: {exc}") from exc


def get_artifact(path: Path, key: str) -> CachedArtifact | None:
    connection = open_database(path)
    try:
        row = connection.execute(
            "SELECT * FROM generated_artifacts WHERE key = ?",
            (key,),
        ).fetchone()
    except sqlite3.Error as exc:
        raise MemoryctlError(f"failed to read cache database {path}: {exc}") from exc
    finally:
        connection.close()
    if row is None:
        return None
    try:
        usage = json.loads(row["usage_json"])
    except json.JSONDecodeError as exc:
        raise MemoryctlError(f"cache database contains invalid usage JSON for {key[:12]}") from exc
    if not isinstance(usage, dict):
        raise MemoryctlError(f"cache database contains invalid usage data for {key[:12]}")
    return CachedArtifact(
        key=str(row["key"]),
        operation=str(row["operation"]),
        text=str(row["text"]),
        model=str(row["model"]),
        effort=str(row["effort"]),
        created_at=str(row["created_at"]),
        elapsed_seconds=float(row["elapsed_seconds"]),
        attempts=int(row["attempts"]),
        usage=usage,
        response_id=(
            str(row["response_id"]) if row["response_id"] is not None else None
        ),
    )


def put_artifact(
    path: Path,
    artifact: CachedArtifact,
    *,
    memory_ids: list[str],
    instructions: str,
    prompt: str,
) -> None:
    connection = open_database(path)
    try:
        connection.execute(
            """
            INSERT OR REPLACE INTO generated_artifacts (
                key, operation, memory_ids_json, model, effort,
                instructions_hash, prompt_hash, text, usage_json, response_id,
                elapsed_seconds, attempts, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact.key,
                artifact.operation,
                json.dumps(memory_ids, separators=(",", ":")),
                artifact.model,
                artifact.effort,
                hashlib.sha256(instructions.encode()).hexdigest(),
                hashlib.sha256(prompt.encode()).hexdigest(),
                artifact.text,
                json.dumps(artifact.usage, separators=(",", ":"), sort_keys=True),
                artifact.response_id,
                artifact.elapsed_seconds,
                artifact.attempts,
                artifact.created_at,
            ),
        )
        connection.commit()
    except sqlite3.Error as exc:
        raise MemoryctlError(f"failed to update cache database {path}: {exc}") from exc
    finally:
        connection.close()
