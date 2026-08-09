from __future__ import annotations

import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from .errors import StreamctlError


def default_state_path() -> Path:
    root = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    current = root / "streamctl" / "streams.sqlite3"
    legacy = root / "codex-streamctl" / "streams.sqlite3"
    if not current.exists() and legacy.exists():
        return legacy
    return current


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
    path = path.expanduser().resolve()
    prepare_state_path(path)
    conn = sqlite3.connect(path, timeout=5.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS streams (
            id TEXT PRIMARY KEY,
            label TEXT,
            tail_position INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS entries (
            stream_id TEXT NOT NULL,
            position INTEGER NOT NULL,
            author TEXT NOT NULL,
            body TEXT NOT NULL,
            reply_to INTEGER,
            created_at INTEGER NOT NULL,
            PRIMARY KEY (stream_id, position),
            FOREIGN KEY (stream_id) REFERENCES streams(id),
            FOREIGN KEY (stream_id, reply_to)
                REFERENCES entries(stream_id, position)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS readers (
            stream_id TEXT NOT NULL,
            reader TEXT NOT NULL,
            ack_through INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            PRIMARY KEY (stream_id, reader),
            FOREIGN KEY (stream_id) REFERENCES streams(id)
        )
        """
    )
    return conn


def now_seconds() -> int:
    return int(time.time())


def decode_entry(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "streamId": row["stream_id"],
        "position": row["position"],
        "author": row["author"],
        "text": row["body"],
        "replyTo": row["reply_to"],
        "createdAt": row["created_at"],
    }


def require_stream(conn: sqlite3.Connection, stream_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM streams WHERE id = ?",
        (stream_id,),
    ).fetchone()
    if row is None:
        raise StreamctlError(f"stream not found: {stream_id}")
    return row


def create_stream(path: Path, label: str | None = None) -> dict[str, Any]:
    stream_id = uuid.uuid4().hex
    created_at = now_seconds()
    conn = open_state(path)
    try:
        conn.execute(
            """
            INSERT INTO streams (id, label, tail_position, created_at)
            VALUES (?, ?, 0, ?)
            """,
            (stream_id, label, created_at),
        )
    finally:
        conn.close()
    return {
        "streamId": stream_id,
        "label": label,
        "tailPosition": 0,
        "createdAt": created_at,
    }


def append_entry(
    path: Path,
    stream_id: str,
    author: str,
    text: str,
    *,
    reply_to: int | None = None,
) -> dict[str, Any]:
    created_at = now_seconds()
    conn = open_state(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        stream = require_stream(conn, stream_id)
        position = int(stream["tail_position"]) + 1
        if reply_to is not None:
            reply = conn.execute(
                """
                SELECT 1 FROM entries
                WHERE stream_id = ? AND position = ?
                """,
                (stream_id, reply_to),
            ).fetchone()
            if reply is None:
                raise StreamctlError(
                    f"reply position not found in stream {stream_id}: {reply_to}"
                )
        conn.execute(
            """
            INSERT INTO entries (
                stream_id, position, author, body, reply_to, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (stream_id, position, author, text, reply_to, created_at),
        )
        conn.execute(
            "UPDATE streams SET tail_position = ? WHERE id = ?",
            (position, stream_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {
        "streamId": stream_id,
        "position": position,
        "author": author,
        "text": text,
        "replyTo": reply_to,
        "createdAt": created_at,
    }


def list_entries(
    path: Path,
    stream_id: str,
    *,
    reader: str | None = None,
    after: int | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    conn = open_state(path)
    try:
        conn.execute("BEGIN")
        stream = require_stream(conn, stream_id)
        tail = int(stream["tail_position"])
        ack_through = 0
        if reader is not None:
            row = conn.execute(
                """
                SELECT ack_through FROM readers
                WHERE stream_id = ? AND reader = ?
                """,
                (stream_id, reader),
            ).fetchone()
            if row is not None:
                ack_through = int(row["ack_through"])
        effective_after = after if after is not None else ack_through
        if effective_after > tail:
            raise StreamctlError(
                f"position {effective_after} is beyond stream tail {tail}"
            )

        sql = """
            SELECT * FROM entries
            WHERE stream_id = ? AND position > ?
            ORDER BY position
        """
        params: list[Any] = [stream_id, effective_after]
        if limit:
            sql += "\nLIMIT ?"
            params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        result = {
            "streamId": stream_id,
            "label": stream["label"],
            "reader": reader,
            "ackThrough": ack_through if reader is not None else None,
            "after": effective_after,
            "lastPosition": rows[-1]["position"] if rows else None,
            "tailPosition": tail,
            "entries": [decode_entry(row) for row in rows],
        }
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def acknowledge(
    path: Path,
    stream_id: str,
    reader: str,
    through: int,
) -> dict[str, Any]:
    updated_at = now_seconds()
    conn = open_state(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        stream = require_stream(conn, stream_id)
        tail = int(stream["tail_position"])
        if through > tail:
            raise StreamctlError(
                f"position {through} is beyond stream tail {tail}"
            )
        row = conn.execute(
            """
            SELECT ack_through FROM readers
            WHERE stream_id = ? AND reader = ?
            """,
            (stream_id, reader),
        ).fetchone()
        previous = int(row["ack_through"]) if row is not None else 0
        ack_through = max(previous, through)
        conn.execute(
            """
            INSERT INTO readers (stream_id, reader, ack_through, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(stream_id, reader) DO UPDATE SET
                ack_through = excluded.ack_through,
                updated_at = excluded.updated_at
            """,
            (stream_id, reader, ack_through, updated_at),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {
        "streamId": stream_id,
        "reader": reader,
        "requestedThrough": through,
        "ackThrough": ack_through,
        "advanced": ack_through > previous,
        "updatedAt": updated_at,
    }
