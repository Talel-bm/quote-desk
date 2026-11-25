"""A tiny job queue in SQLite: enough for one background worker, no broker needed.

The web request that receives an RFQ only enqueues a job and returns at once; the
worker claims jobs one at a time. The idempotency key stops the same job from being
queued twice (e.g. the same email submitted again).
"""

import json
import sqlite3
from typing import Any

MAX_ATTEMPTS = 3


def enqueue(conn: sqlite3.Connection, kind: str, payload: dict[str, Any], key: str) -> bool:
    """Queue a job; return False if a job with this key already exists."""
    cursor = conn.execute(
        "INSERT OR IGNORE INTO jobs (kind, payload, idempotency_key) VALUES (?, ?, ?)",
        (kind, json.dumps(payload, sort_keys=True), key),
    )
    return cursor.rowcount == 1


def claim(conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Take the oldest queued job and mark it running, in one statement (no double claim)."""
    row = conn.execute(
        "UPDATE jobs SET status = 'running', attempts = attempts + 1"
        " WHERE id = (SELECT id FROM jobs WHERE status = 'queued' ORDER BY id LIMIT 1)"
        " RETURNING id, kind, payload, attempts"
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "kind": row["kind"],
        "payload": json.loads(row["payload"]),
        "attempts": row["attempts"],
    }


def complete(conn: sqlite3.Connection, job_id: int) -> None:
    conn.execute("UPDATE jobs SET status = 'done', error = NULL WHERE id = ?", (job_id,))


def fail(conn: sqlite3.Connection, job_id: int, error: str) -> None:
    """Record a failure: back to the queue unless it has used all its attempts."""
    conn.execute(
        "UPDATE jobs SET error = ?,"
        " status = CASE WHEN attempts >= ? THEN 'failed' ELSE 'queued' END WHERE id = ?",
        (error, MAX_ATTEMPTS, job_id),
    )
