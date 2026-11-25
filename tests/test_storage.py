"""Event log, projections and job queue (storage/)."""

import sqlite3
from datetime import datetime

import pytest

from quote_desk.core.events import NewEvent
from quote_desk.storage import jobs, projections
from quote_desk.storage.db import connect, migrate, transaction
from quote_desk.storage.events import (
    ConcurrencyError,
    append,
    read_after,
    read_stream,
    verify_chain,
)

T0 = datetime(2026, 11, 20, 9, 0)


@pytest.fixture
def conn(tmp_path):
    return connect(tmp_path / "app.sqlite")


def email(n: int = 1) -> NewEvent:
    return NewEvent(
        stream=f"run:R-{n}",
        type="email.received",
        actor="system:inbox",
        run_id=f"R-{n}",
        sim_at=T0,
        payload={"message_id": f"m{n}", "sender": "a@b.com", "subject": "RFQ", "body": "x"},
    )


def drafted(quote: str = "Q-1", run: str = "R-1") -> NewEvent:
    return NewEvent(
        stream=f"quote:{quote}",
        type="quote.drafted",
        actor="agent:quote",
        run_id=run,
        sim_at=T0,
        payload={
            "quote_id": quote,
            "customer": "Acme",
            "recipient": "buyer@acme.com",
            "total": 100.0,
            "reply": "Hi",
            "lines": [{"family": "transformer", "qty": 2}],
        },
    )


def test_migrations_apply_once(conn):
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    assert migrate(conn) == 1  # running again changes nothing


def test_append_assigns_global_and_stream_order(conn):
    with transaction(conn):
        a, b = append(conn, [email(1), email(2)])
        (c,) = append(conn, [drafted()])
    assert (a.position, b.position, c.position) == (1, 2, 3)
    assert (a.stream_seq, b.stream_seq, c.stream_seq) == (1, 1, 1)
    assert [e.position for e in read_after(conn, 1)] == [2, 3]
    assert read_stream(conn, "quote:Q-1")[0].payload["total"] == 100.0


def test_append_needs_a_transaction(conn):
    with pytest.raises(RuntimeError):
        append(conn, [email()])


def test_unknown_type_and_bad_payload_are_rejected(conn):
    with pytest.raises(ValueError), transaction(conn):
        append(conn, [email().model_copy(update={"type": "made.up"})])
    with pytest.raises(ValueError), transaction(conn):
        append(conn, [email().model_copy(update={"payload": {"sender": "x"}})])
    assert read_after(conn) == []  # nothing half-written


def test_concurrency_check_refuses_a_stale_writer(conn):
    with transaction(conn):
        append(conn, [drafted()])
    with pytest.raises(ConcurrencyError), transaction(conn):
        append(conn, [drafted()], expect={"quote:Q-1": 0})  # caller saw an older version
    with transaction(conn):
        append(conn, [drafted()], expect={"quote:Q-1": 1})


def test_history_cannot_be_updated_or_deleted(conn):
    with transaction(conn):
        append(conn, [email()])
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE events SET actor = 'someone' WHERE position = 1")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM events")


def test_verify_chain_finds_the_first_tampered_event(conn):
    with transaction(conn):
        append(conn, [email(1), email(2), email(3)])
    assert verify_chain(conn) is None
    conn.execute("DROP TRIGGER events_no_update")  # an attacker with write access
    conn.execute("UPDATE events SET payload = replace(payload, 'm2', 'evil') WHERE position = 2")
    assert verify_chain(conn) == 2


def test_projections_rebuild_equals_live(conn):
    with transaction(conn):
        append(conn, [email(1), drafted("Q-1", "R-1")])
        append(
            conn,
            [
                NewEvent(
                    stream="quote:Q-1",
                    type="policy.decided",
                    actor="agent:quote",
                    run_id="R-1",
                    sim_at=T0,
                    payload={
                        "quote_id": "Q-1",
                        "bucket": "ready",
                        "rule_ids": ["R-1"],
                        "reasons": ["ok"],
                        "policy_version": "v1",
                        "flags": [],
                    },
                )
            ],
        )
    live = projections.dump(conn)
    assert live["inbox_items"][0][5] == "ready"
    projections.rebuild(conn)
    assert projections.dump(conn) == live


def test_jobs_are_claimed_once_and_retried_then_failed(conn):
    assert jobs.enqueue(conn, "rfq", {"x": 1}, key="m1")
    assert not jobs.enqueue(conn, "rfq", {"x": 1}, key="m1")  # same key: ignored
    job = jobs.claim(conn)
    assert job["payload"] == {"x": 1} and jobs.claim(conn) is None
    for _ in range(jobs.MAX_ATTEMPTS - 1):
        jobs.fail(conn, job["id"], "boom")
        job = jobs.claim(conn)
    jobs.fail(conn, job["id"], "boom")
    assert jobs.claim(conn) is None
    assert conn.execute("SELECT status FROM jobs").fetchone()[0] == "failed"
