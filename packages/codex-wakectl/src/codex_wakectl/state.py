from __future__ import annotations

import json
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from .errors import WakectlError
from .parsing import now_seconds


JOB_COLUMNS = {
    "status": "status",
    "condition": "condition_json",
    "action": "action_json",
    "targetThreadId": "target_thread_id",
    "message": "message",
    "endpoint": "endpoint",
    "timeout": "timeout",
    "allowActive": "allow_active",
    "createdAt": "created_at",
    "updatedAt": "updated_at",
    "firedAt": "fired_at",
    "fireCount": "fire_count",
    "lastFiredAt": "last_fired_at",
    "lastTurnId": "last_turn_id",
    "lastClientMessageId": "last_client_message_id",
    "lastDeliveryMode": "last_delivery_mode",
    "lastEventItemId": "last_event_item_id",
    "lastReason": "last_reason",
    "lastError": "last_error",
    "lastTokensUsedBucket": "last_tokens_used_bucket",
    "lastTimeUsedBucket": "last_time_used_bucket",
    "leaseOwner": "lease_owner",
    "leaseStartedAt": "lease_started_at",
    "leaseUntil": "lease_until",
}

OPTIONAL_JOB_FIELDS = [
    "firedAt",
    "lastFiredAt",
    "lastTurnId",
    "lastClientMessageId",
    "lastDeliveryMode",
    "lastEventItemId",
    "lastReason",
    "lastError",
    "lastTokensUsedBucket",
    "lastTimeUsedBucket",
    "timeout",
    "leaseOwner",
    "leaseStartedAt",
    "leaseUntil",
]


def default_state_path() -> Path:
    root = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return root / "codex-wakectl" / "jobs.sqlite3"


def prepare_state_path(path: Path) -> None:
    is_default = path == default_state_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if is_default:
        path.parent.chmod(0o700)

    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    os.close(fd)
    if is_default:
        path.chmod(0o600)


def open_state(path: Path) -> sqlite3.Connection:
    prepare_state_path(path)
    conn = sqlite3.connect(path, timeout=5.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            condition_json TEXT NOT NULL,
            action_json TEXT,
            target_thread_id TEXT NOT NULL,
            message TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            timeout REAL,
            allow_active INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            fired_at INTEGER,
            fire_count INTEGER NOT NULL DEFAULT 0,
            last_fired_at INTEGER,
            last_turn_id TEXT,
            last_client_message_id TEXT,
            last_delivery_mode TEXT,
            last_event_item_id TEXT,
            last_reason TEXT,
            last_error TEXT,
            last_tokens_used_bucket INTEGER,
            last_time_used_bucket INTEGER,
            lease_owner TEXT,
            lease_started_at INTEGER,
            lease_until INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS jobs_pending_idx
        ON jobs(status, lease_until, created_at)
        """
    )
    ensure_column(conn, "timeout", "REAL")
    ensure_column(conn, "allow_active", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "last_client_message_id", "TEXT")
    ensure_column(conn, "last_delivery_mode", "TEXT")
    ensure_column(conn, "action_json", "TEXT")
    ensure_column(conn, "last_event_item_id", "TEXT")
    return conn


def ensure_column(conn: sqlite3.Connection, name: str, declaration: str) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
    if name not in columns:
        conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} {declaration}")


def decode_job(row: sqlite3.Row) -> dict[str, Any]:
    action_json = row["action_json"]
    if action_json is None:
        action = {
            "type": "input",
            "message": row["message"],
            **({"allowActive": True} if bool(row["allow_active"]) else {}),
            "legacy": True,
        }
    else:
        action = json.loads(action_json)
    job: dict[str, Any] = {
        "id": row["id"],
        "status": row["status"],
        "condition": json.loads(row["condition_json"]),
        "action": action,
        "targetThreadId": row["target_thread_id"],
        "endpoint": row["endpoint"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "fireCount": row["fire_count"],
    }
    for key in OPTIONAL_JOB_FIELDS:
        value = row[JOB_COLUMNS[key]]
        if value is not None:
            job[key] = value
    return job


def encode_value(key: str, value: Any) -> Any:
    if key == "condition":
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    if key == "action":
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return value


def insert_job(state_path: Path, job: dict[str, Any]) -> None:
    conn = open_state(state_path)
    try:
        conn.execute(
            """
            INSERT INTO jobs (
                id, status, condition_json, action_json, target_thread_id, message, endpoint,
                timeout, allow_active,
                created_at, updated_at, fired_at, fire_count, last_fired_at,
                last_turn_id, last_reason, last_error, last_tokens_used_bucket,
                last_time_used_bucket, lease_owner, lease_started_at, lease_until,
                last_client_message_id, last_delivery_mode, last_event_item_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job["id"],
                job["status"],
                encode_value("condition", job["condition"]),
                encode_value("action", job["action"]),
                job["targetThreadId"],
                job["action"].get("message", ""),
                job["endpoint"],
                job.get("timeout"),
                int(bool(job["action"].get("allowActive"))),
                job["createdAt"],
                job["updatedAt"],
                job.get("firedAt"),
                int(job.get("fireCount") or 0),
                job.get("lastFiredAt"),
                job.get("lastTurnId"),
                job.get("lastReason"),
                job.get("lastError"),
                job.get("lastTokensUsedBucket"),
                job.get("lastTimeUsedBucket"),
                job.get("leaseOwner"),
                job.get("leaseStartedAt"),
                job.get("leaseUntil"),
                job.get("lastClientMessageId"),
                job.get("lastDeliveryMode"),
                job.get("lastEventItemId"),
            ),
        )
    finally:
        conn.close()


def list_jobs(state_path: Path, *, include_all: bool = False) -> list[dict[str, Any]]:
    conn = open_state(state_path)
    try:
        where = (
            ""
            if include_all
            else "WHERE status IN ('pending', 'failed', 'uncertain')"
        )
        rows = conn.execute(
            f"""
            SELECT * FROM jobs
            {where}
            ORDER BY created_at, id
            """
        ).fetchall()
        return [decode_job(row) for row in rows]
    finally:
        conn.close()


def cancel_job(state_path: Path, job_id: str) -> bool:
    ts = now_seconds()
    conn = open_state(state_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            """
            UPDATE jobs
            SET status = 'canceled',
                updated_at = ?,
                lease_owner = NULL,
                lease_started_at = NULL,
                lease_until = NULL
            WHERE id = ?
              AND status = 'pending'
              AND (lease_owner IS NULL OR lease_until IS NULL OR lease_until <= ?)
            """,
            (ts, job_id, ts),
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def claim_pending_jobs(
    state_path: Path,
    lease_seconds: int,
    limit: int | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    owner = uuid.uuid4().hex
    ts = now_seconds()
    conn = open_state(state_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        query = """
            SELECT * FROM jobs
            WHERE status = 'pending'
              AND (lease_owner IS NULL OR lease_until IS NULL OR lease_until <= ?)
            ORDER BY created_at, id
            """
        params: list[Any] = [ts]
        if limit is not None:
            query += "\nLIMIT ?"
            params.append(limit)
        rows = conn.execute(query, params).fetchall()
        conn.executemany(
            """
            UPDATE jobs
            SET lease_owner = ?,
                lease_started_at = ?,
                lease_until = ?,
                updated_at = ?
            WHERE id = ? AND status = 'pending'
            """,
            [(owner, ts, ts + lease_seconds, ts, row["id"]) for row in rows],
        )
        conn.commit()
        return owner, [decode_job(row) for row in rows]
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_claimed_job(
    state_path: Path,
    job_id: str,
    owner: str,
    updates: dict[str, Any] | None = None,
) -> bool:
    updates = updates or {}
    unknown = [key for key in updates if key not in JOB_COLUMNS]
    if unknown:
        raise WakectlError("unknown job update field: " + ", ".join(sorted(unknown)))

    ts = now_seconds()
    assignments = [
        "updated_at = ?",
        "lease_owner = NULL",
        "lease_started_at = NULL",
        "lease_until = NULL",
    ]
    params: list[Any] = [ts]
    for key, value in updates.items():
        assignments.append(f"{JOB_COLUMNS[key]} = ?")
        params.append(encode_value(key, value))
    params.extend([job_id, owner])

    conn = open_state(state_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            f"""
            UPDATE jobs
            SET {", ".join(assignments)}
            WHERE id = ? AND lease_owner = ? AND status = 'pending'
            """,
            params,
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def renew_claimed_job(
    state_path: Path,
    job_id: str,
    owner: str,
    lease_seconds: int,
) -> bool:
    ts = now_seconds()
    conn = open_state(state_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            """
            UPDATE jobs
            SET lease_until = ?, updated_at = ?
            WHERE id = ? AND lease_owner = ? AND status = 'pending'
            """,
            (ts + lease_seconds, ts, job_id, owner),
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
