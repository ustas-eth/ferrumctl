"""Caller-owned recovery overrides; native selections remain owned by Codex."""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .errors import OperationError, ThreadctlError

# Codex records these selections itself, including before the first model turn.
# Replaying launch values would overwrite later changes made by another client.
NATIVE_KEYS = frozenset({
    "model", "model_provider", "model_reasoning_effort", "approval_policy",
    "approvals_reviewer", "sandbox_mode", "default_permissions", "cwd",
})
SECRET_KEYS = frozenset({
    "api_key", "apikey", "bearer_token", "experimental_bearer_token",
    "password", "authorization", "x_api_key",
})
ANY_REVISION = object()


def default_state_path() -> Path:
    root = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return root / "codex-threadctl" / "threads.sqlite3"


def recovery_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """Keep only supplementary settings, rejecting known inline credentials."""
    result = {key: value for key, value in (config or {}).items() if key not in NATIVE_KEYS}

    def check(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "env_http_headers":
                    continue  # Header values here are environment variable names.
                if key.lower().replace("-", "_") in SECRET_KEYS and child:
                    raise ThreadctlError(
                        "recovery settings contain inline credentials; "
                        "use environment-based credentials or --no-recovery"
                    )
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)

    check(result)
    try:
        json.dumps(result, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ThreadctlError("recovery settings must be JSON-compatible") from exc
    return result


@contextmanager
def database(path: Path, *, write: bool = False) -> Iterator[sqlite3.Connection]:
    path = path.expanduser().resolve()
    connection = None
    try:
        if write:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if path == default_state_path().expanduser().resolve():
                path.parent.chmod(0o700)
            descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
            os.close(descriptor)
            if path == default_state_path().expanduser().resolve():
                path.chmod(0o600)
        connection = sqlite3.connect(
            path.as_uri() + ("?mode=rw" if write else "?mode=ro"),
            uri=True, timeout=5,
        )
        connection.row_factory = sqlite3.Row
        if write:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS recovery_settings (
                    endpoint TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    updated_at INTEGER NOT NULL,
                    revision TEXT NOT NULL,
                    PRIMARY KEY (endpoint, thread_id)
                )
            """)
        yield connection
        if write:
            connection.commit()
    except (OSError, sqlite3.Error) as exc:
        raise ThreadctlError(f"cannot access recovery state {path}: {exc}") from exc
    finally:
        if connection is not None:
            connection.close()


def read_recovery(path: Path, endpoint: str, thread_id: str) -> dict[str, Any] | None:
    try:
        exists = path.expanduser().exists()
    except OSError as exc:
        raise ThreadctlError(f"cannot access recovery state {path}: {exc}") from exc
    if not exists:
        return None
    with database(path) as connection:
        row = connection.execute(
            "SELECT config_json, updated_at, revision FROM recovery_settings WHERE endpoint=? AND thread_id=?",
            (endpoint, thread_id),
        ).fetchone()
    if row is None:
        return None
    try:
        config = json.loads(row["config_json"])
        if not isinstance(config, dict) or any(key in NATIVE_KEYS for key in config):
            raise ValueError("invalid supplementary settings")
        config = recovery_config(config)
    except (TypeError, ValueError) as exc:
        raise ThreadctlError("invalid saved recovery settings; inspect or forget the record") from exc
    return {"config": config, "updatedAt": row["updated_at"], "revision": row["revision"]}


def public_recovery(
    path: Path, endpoint: str, thread_id: str,
    record: dict[str, Any] | None, *, values: bool = False,
) -> dict[str, Any]:
    result = {
        "source": "local-state", "statePath": str(path.expanduser().resolve()),
        "endpoint": endpoint, "threadId": thread_id,
        "outcome": "saved" if record else "notFound",
        "keys": sorted(record["config"]) if record else [],
    }
    if record:
        result["updatedAt"] = record["updatedAt"]
        if values:
            result["config"] = record["config"]
    return result


def write_recovery(
    path: Path, endpoint: str, thread_id: str, config: dict[str, Any],
    *, expected_revision: Any = ANY_REVISION,
) -> dict[str, Any]:
    config = recovery_config(config)
    updated_at = int(time.time())
    with database(path, write=True) as connection:
        connection.execute("BEGIN IMMEDIATE")
        if expected_revision is not ANY_REVISION:
            row = connection.execute(
                "SELECT revision FROM recovery_settings WHERE endpoint=? AND thread_id=?",
                (endpoint, thread_id),
            ).fetchone()
            if (row["revision"] if row else None) != expected_revision:
                raise ThreadctlError("recovery record changed during loading; newer settings were retained")
        if config:
            connection.execute(
                "INSERT INTO recovery_settings VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(endpoint, thread_id) DO UPDATE SET "
                "config_json=excluded.config_json, updated_at=excluded.updated_at, "
                "revision=excluded.revision",
                (endpoint, thread_id, json.dumps(config, allow_nan=False), updated_at, str(uuid.uuid4())),
            )
        else:
            connection.execute("DELETE FROM recovery_settings WHERE endpoint=? AND thread_id=?",
                               (endpoint, thread_id))
    return public_recovery(path, endpoint, thread_id,
                           {"config": config, "updatedAt": updated_at} if config else None)


def remember_after_operation(
    path: Path, endpoint: str, thread_id: str, config: dict[str, Any], operation: str,
    *, expected_revision: Any = ANY_REVISION,
) -> dict[str, Any]:
    try:
        return write_recovery(path, endpoint, thread_id, config, expected_revision=expected_revision)
    except ThreadctlError as exc:
        raise OperationError(
            f"thread {operation} but recovery settings could not be saved; "
            "retain the thread id and repair the record, not repeat the operation",
            code="recoverySaveFailed", outcome="partial", threadId=thread_id,
            recoveryError=str(exc),
        ) from exc
