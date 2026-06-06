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


def open_state(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
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
    return conn


def ensure_column(conn: sqlite3.Connection, name: str, declaration: str) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
    if name not in columns:
        conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} {declaration}")


def decode_job(row: sqlite3.Row) -> dict[str, Any]:
    job: dict[str, Any] = {
        "id": row["id"],
        "status": row["status"],
        "condition": json.loads(row["condition_json"]),
        "targetThreadId": row["target_thread_id"],
        "message": row["message"],
        "endpoint": row["endpoint"],
        "allowActive": bool(row["allow_active"]),
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
    return value


def insert_job(state_path: Path, job: dict[str, Any]) -> None:
    conn = open_state(state_path)
    try:
        conn.execute(
            """
            INSERT INTO jobs (
                id, status, condition_json, target_thread_id, message, endpoint,
                timeout, allow_active,
                created_at, updated_at, fired_at, fire_count, last_fired_at,
                last_turn_id, last_reason, last_error, last_tokens_used_bucket,
                last_time_used_bucket, lease_owner, lease_started_at, lease_until
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job["id"],
                job["status"],
                encode_value("condition", job["condition"]),
                job["targetThreadId"],
                job["message"],
                job["endpoint"],
                job.get("timeout"),
                int(bool(job.get("allowActive"))),
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
            ),
        )
    finally:
        conn.close()


def list_jobs(state_path: Path, *, include_all: bool = False) -> list[dict[str, Any]]:
    conn = open_state(state_path)
    try:
        where = "" if include_all else "WHERE status = 'pending'"
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
            """,
            (now_seconds(), job_id),
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
