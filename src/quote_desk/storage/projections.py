"""Projections: the tables the screens read, rebuilt from events.

Each projector turns one event into a change in a screen table. They run in the same
transaction as the event (see `storage.events.append`). Because the tables are fully
derived from the log, `rebuild()` can erase and replay them, and a test checks that a
rebuild gives exactly what was built live.
"""

import json
import sqlite3

from quote_desk.core.events import StoredEvent
from quote_desk.storage.events import PROJECTORS, projector, read_after

PROJECTION_TABLES = ("inbox_items", "runs", "run_steps", "quote_view")


def merge_quote_view(conn: sqlite3.Connection, quote_id: str, **fields: object) -> None:
    """Add fields to the quote detail document (a JSON blob per quote)."""
    row = conn.execute("SELECT data FROM quote_view WHERE quote_id = ?", (quote_id,)).fetchone()
    data = json.loads(row["data"]) if row else {"quote_id": quote_id, "history": []}
    data.update(fields)
    conn.execute(
        "INSERT INTO quote_view (quote_id, data) VALUES (?, ?)"
        " ON CONFLICT(quote_id) DO UPDATE SET data = excluded.data",
        (quote_id, json.dumps(data, sort_keys=True)),
    )


def add_history(conn: sqlite3.Connection, quote_id: str, event: StoredEvent, text: str) -> None:
    row = conn.execute("SELECT data FROM quote_view WHERE quote_id = ?", (quote_id,)).fetchone()
    history = json.loads(row["data"])["history"] if row else []
    history.append({"position": event.position, "at": event.sim_at.isoformat(), "text": text})
    merge_quote_view(conn, quote_id, history=history)


@projector("email.received")
def run_started(conn: sqlite3.Connection, event: StoredEvent) -> None:
    if event.run_id:
        conn.execute(
            "INSERT OR IGNORE INTO runs (run_id, stream, status, started_at, last_position)"
            " VALUES (?, ?, 'running', ?, ?)",
            (event.run_id, event.stream, event.sim_at.isoformat(), event.position),
        )


@projector("step.finished")
def step_finished(conn: sqlite3.Connection, event: StoredEvent) -> None:
    p = event.payload
    conn.execute(
        "INSERT INTO run_steps (run_id, position, step, ok, detail, seconds) VALUES (?,?,?,?,?,?)",
        (event.run_id, event.position, p["step"], int(p["ok"]), p["detail"], p["seconds"]),
    )
    conn.execute(
        "UPDATE runs SET last_position = ? WHERE run_id = ?", (event.position, event.run_id)
    )


@projector("run.finished")
def run_finished(conn: sqlite3.Connection, event: StoredEvent) -> None:
    conn.execute(
        "UPDATE runs SET status = ?, last_position = ? WHERE run_id = ?",
        (event.payload["status"], event.position, event.run_id),
    )


@projector("quote.drafted")
def quote_drafted(conn: sqlite3.Connection, event: StoredEvent) -> None:
    p = event.payload
    summary = ", ".join(f"{line['family']} x{line['qty']}" for line in p["lines"])
    conn.execute(
        "INSERT OR REPLACE INTO inbox_items (quote_id, run_id, customer, summary, total, bucket,"
        " last_position) VALUES (?, ?, ?, ?, ?, 'pending', ?)",
        (p["quote_id"], event.run_id, p["customer"], summary, p["total"], event.position),
    )
    merge_quote_view(
        conn, p["quote_id"], **{k: p[k] for k in ("customer", "lines", "total", "reply")}
    )
    add_history(conn, p["quote_id"], event, "draft prepared by agent:quote")


@projector("policy.decided")
def policy_decided(conn: sqlite3.Connection, event: StoredEvent) -> None:
    p = event.payload
    conn.execute(
        "UPDATE inbox_items SET bucket = ?, rule_ids = ?, reasons = ?, last_position = ?"
        " WHERE quote_id = ?",
        (
            p["bucket"],
            json.dumps(p["rule_ids"]),
            json.dumps(p["flags"] + p["reasons"]),
            event.position,
            p["quote_id"],
        ),
    )
    merge_quote_view(
        conn,
        p["quote_id"],
        policy={k: p[k] for k in ("bucket", "rule_ids", "reasons", "flags", "policy_version")},
    )
    add_history(conn, p["quote_id"], event, f"policy {p['policy_version']}: {p['bucket']}")


@projector("quote.decided")
def quote_decided(conn: sqlite3.Connection, event: StoredEvent) -> None:
    p = event.payload
    conn.execute(
        "UPDATE inbox_items SET bucket = ?, last_position = ? WHERE quote_id = ?",
        (p["decision"], event.position, p["quote_id"]),
    )
    note = f" ({p['reason']})" if p["reason"] else ""
    add_history(conn, p["quote_id"], event, f"{p['decision']} by {event.actor}{note}")


@projector("email.staged")
def email_staged(conn: sqlite3.Connection, event: StoredEvent) -> None:
    add_history(
        conn, event.payload["quote_id"], event, f"reply queued to {event.payload['recipient']}"
    )


def rebuild(conn: sqlite3.Connection) -> None:
    """Erase every projection table and replay the whole log into them."""
    for table in PROJECTION_TABLES:
        conn.execute(f"DELETE FROM {table}")  # noqa: S608 (fixed table names)
    position = 0
    while batch := read_after(conn, position):
        for event in batch:
            for fn in PROJECTORS.get(event.type, []):
                fn(conn, event)
        position = batch[-1].position


def dump(conn: sqlite3.Connection) -> dict[str, list[tuple[object, ...]]]:
    """Every projection table's rows, sorted: used to compare rebuild with live."""
    return {
        table: sorted(tuple(r) for r in conn.execute(f"SELECT * FROM {table}"))  # noqa: S608
        for table in PROJECTION_TABLES
    }
