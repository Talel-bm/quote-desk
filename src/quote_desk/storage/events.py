"""The event log: append events, read them back, and verify nothing was altered.

Each event stores the hash of the event before it (a hash chain). Changing or deleting
an old event therefore breaks every hash after it, and `verify_chain()` finds the first
broken one. Triggers in the database also refuse UPDATE and DELETE on the table.

Projections (inbox, runs, quote view) are updated by projector functions in the same
transaction as the events they read, so a screen never shows half of a change.
"""

import hashlib
import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from quote_desk.core.events import NewEvent, StoredEvent, validate_payload

GENESIS = "0" * 64  # the "previous hash" of the very first event
SCHEMA_V = 1

Projector = Callable[[sqlite3.Connection, StoredEvent], None]
PROJECTORS: dict[str, list[Projector]] = {}


class ConcurrencyError(Exception):
    """A stream changed since the caller last read it (someone else acted first)."""


def projector(*event_types: str) -> Callable[[Projector], Projector]:
    """Register a function to run for every new event of these types."""

    def register(fn: Projector) -> Projector:
        for event_type in event_types:
            PROJECTORS.setdefault(event_type, []).append(fn)
        return fn

    return register


def canonical(fields: dict[str, Any]) -> str:
    """JSON with sorted keys and no spaces: the same fields always give the same text."""
    return json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str)


def event_hash(prev_hash: str, fields: dict[str, Any]) -> str:
    """SHA-256 of the previous hash followed by this event's fields."""
    return hashlib.sha256((prev_hash + canonical(fields)).encode("utf-8")).hexdigest()


def hashed_fields(row: dict[str, Any]) -> dict[str, Any]:
    """The fields covered by the hash (everything except position and the hashes)."""
    keys = ("stream", "stream_seq", "type", "actor", "run_id", "causation", "sim_at")
    fields = {k: row[k] for k in keys}
    fields |= {"wall_at": row["wall_at"], "schema_v": row["schema_v"]}
    fields["payload"] = (
        row["payload"] if isinstance(row["payload"], dict) else json.loads(row["payload"])
    )
    return fields


def last_hash(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT hash FROM events ORDER BY position DESC LIMIT 1").fetchone()
    return row["hash"] if row else GENESIS


def stream_version(conn: sqlite3.Connection, stream: str) -> int:
    """How many events a stream has (0 if none)."""
    row = conn.execute(
        "SELECT MAX(stream_seq) AS v FROM events WHERE stream = ?", (stream,)
    ).fetchone()
    return int(row["v"] or 0)


def append(
    conn: sqlite3.Connection,
    events: list[NewEvent],
    expect: dict[str, int] | None = None,
) -> list[StoredEvent]:
    """Store events at the end of the log and run their projectors.

    Must be called inside `storage.db.transaction()`. `expect` maps a stream to the
    version the caller last saw; if the stream moved on since, nothing is written and
    ConcurrencyError is raised (e.g. two people approving the same quote).
    """
    if not conn.in_transaction:
        raise RuntimeError("append() must run inside storage.db.transaction()")
    for stream, version in (expect or {}).items():
        if stream_version(conn, stream) != version:
            raise ConcurrencyError(f"{stream} changed since version {version}")

    stored = []
    prev = last_hash(conn)
    for event in events:
        row: dict[str, Any] = {
            "stream": event.stream,
            "stream_seq": stream_version(conn, event.stream) + 1,
            "type": event.type,
            "actor": event.actor,
            "run_id": event.run_id,
            "causation": event.causation,
            "sim_at": event.sim_at.isoformat(),
            "wall_at": datetime.now(UTC).isoformat(),
            "schema_v": SCHEMA_V,
            "payload": validate_payload(event.type, event.payload),
        }
        row["prev_hash"] = prev
        row["hash"] = event_hash(prev, hashed_fields(row))
        cursor = conn.execute(
            "INSERT INTO events (stream, stream_seq, type, actor, run_id, causation, sim_at,"
            " wall_at, schema_v, payload, prev_hash, hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row["stream"],
                row["stream_seq"],
                row["type"],
                row["actor"],
                row["run_id"],
                row["causation"],
                row["sim_at"],
                row["wall_at"],
                row["schema_v"],
                canonical(row["payload"]),
                prev,
                row["hash"],
            ),
        )
        saved = StoredEvent(position=int(cursor.lastrowid or 0), **row)
        for fn in PROJECTORS.get(saved.type, []):
            fn(conn, saved)
        stored.append(saved)
        prev = row["hash"]
    return stored


def to_event(row: sqlite3.Row) -> StoredEvent:
    data = dict(row)
    data["payload"] = json.loads(data["payload"])
    return StoredEvent(**data)


def read_after(conn: sqlite3.Connection, position: int = 0, limit: int = 500) -> list[StoredEvent]:
    """Events after a position, oldest first (used by the live stream and replays)."""
    rows = conn.execute(
        "SELECT * FROM events WHERE position > ? ORDER BY position LIMIT ?", (position, limit)
    ).fetchall()
    return [to_event(r) for r in rows]


def read_stream(conn: sqlite3.Connection, stream: str) -> list[StoredEvent]:
    rows = conn.execute(
        "SELECT * FROM events WHERE stream = ? ORDER BY stream_seq", (stream,)
    ).fetchall()
    return [to_event(r) for r in rows]


def verify_chain(conn: sqlite3.Connection) -> int | None:
    """Recompute every hash; return the position of the first bad event, or None if intact."""
    prev = GENESIS
    for row in conn.execute("SELECT * FROM events ORDER BY position"):
        data = dict(row)
        if data["prev_hash"] != prev or data["hash"] != event_hash(prev, hashed_fields(data)):
            return int(data["position"])
        prev = data["hash"]
    return None
