"""Use case: a person approves or rejects a drafted quote.

The policy is checked again at decision time for the person acting (an estimator
cannot approve what needs a senior). An approval and its outbox row are written in the
same transaction, and the outbox row points at the approval event: there is no other
way into the outbox (ADR 5, ADR 8).
"""

import json
import sqlite3

from quote_desk.core.clock import Clock
from quote_desk.core.events import NewEvent
from quote_desk.storage.db import transaction
from quote_desk.storage.events import append, read_stream, stream_version
from quote_desk.workforce.policy import Policy, Principal, decide
from quote_desk.workforce.quote import margin_of


class NotAllowed(Exception):
    """The policy does not permit this person to take this action."""


def quote_facts(conn: sqlite3.Connection, quote_id: str) -> tuple[dict, list[str]]:
    """The latest draft payload and its warnings, read from the quote's events."""
    drafted, flags = None, []
    for event in read_stream(conn, f"quote:{quote_id}"):
        if event.type == "quote.drafted":
            drafted = event.payload
        elif event.type == "policy.decided":
            flags = event.payload["flags"]
    if drafted is None:
        raise KeyError(f"no draft for {quote_id}")
    return drafted, flags


def decide_quote(
    conn: sqlite3.Connection,
    quote_id: str,
    decision: str,
    role: str,
    policy: Policy,
    clock: Clock,
    reason: str = "",
    expected_version: int | None = None,
) -> int:
    """Record an approval or rejection; on approval, stage the reply in the outbox.

    The recipient is the contact on the customer record (set when the draft was made).

    Returns the position of the decision event. `expected_version` is the quote
    version the person was looking at; if it changed meanwhile, nothing is written.
    """
    if decision not in ("approved", "rejected"):
        raise ValueError("decision must be 'approved' or 'rejected'")
    stream = f"quote:{quote_id}"
    with transaction(conn):
        drafted, flags = quote_facts(conn, quote_id)
        if decision == "approved":
            total = drafted["total"]
            context = {
                "margin": margin_of(drafted["lines"], total),
                "total": total,
                "flag_count": len(flags),
            }
            verdict = decide(
                policy, Principal(kind="human", role=role), "quote.approve_send", context
            )
            if not verdict.allowed or not drafted["recipient"]:
                raise NotAllowed(
                    "; ".join(verdict.reasons) or "no rule permits this, or no customer on file"
                )
        expect = {stream: expected_version} if expected_version is not None else None
        (event,) = append(
            conn,
            [
                NewEvent(
                    stream=stream,
                    type="quote.decided",
                    actor=f"user:{role}",
                    sim_at=clock.now(),
                    payload={"quote_id": quote_id, "decision": decision, "reason": reason},
                )
            ],
            expect=expect,
        )
        if decision == "approved":
            conn.execute(
                "INSERT INTO outbox (key, quote_id, approval_position, recipient, body)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    f"{quote_id}:{event.position}",
                    quote_id,
                    event.position,
                    drafted["recipient"],
                    drafted["reply"],
                ),
            )
            append(
                conn,
                [
                    NewEvent(
                        stream=stream,
                        type="email.staged",
                        actor="system:outbox",
                        sim_at=clock.now(),
                        causation=event.position,
                        payload={
                            "quote_id": quote_id,
                            "recipient": drafted["recipient"],
                            "approval_position": event.position,
                        },
                    )
                ],
            )
    return event.position


def version(conn: sqlite3.Connection, quote_id: str) -> int:
    return stream_version(conn, f"quote:{quote_id}")


def outbox(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM outbox ORDER BY approval_position")]


def inbox(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM inbox_items ORDER BY last_position DESC").fetchall()
    return [
        dict(r) | {"rule_ids": json.loads(r["rule_ids"]), "reasons": json.loads(r["reasons"])}
        for r in rows
    ]
