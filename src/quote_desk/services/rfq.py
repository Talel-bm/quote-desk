"""Use cases for an incoming RFQ: submit it, then process it step by step.

`submit_rfq` only records the email and queues a job, so the web request returns at
once. `process_rfq` (run by the worker) does the work in steps; each step is its own
transaction ending with a `step.finished` event, so the screen can show progress live.

This module is the only place where intake, forge and workforce meet (ADR 2).
"""

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import pandas as pd

from quote_desk.core.clock import Clock
from quote_desk.core.events import NewEvent
from quote_desk.core.quote import Customer, PricedLine
from quote_desk.forge.baseline import price_line
from quote_desk.intake.extract import ExtractionError, extract
from quote_desk.intake.llm import LLMClient
from quote_desk.intake.screen import screen
from quote_desk.storage import jobs
from quote_desk.storage.db import transaction
from quote_desk.storage.events import append, read_stream
from quote_desk.workforce.policy import Policy
from quote_desk.workforce.quote import draft

UNKNOWN = Customer(
    customer_id="", name="Unknown sender", segment="other", email_domain="", contact_email=""
)


@dataclass
class Deps:
    """Everything a run needs from outside, passed in so tests can use fakes."""

    llm: LLMClient
    policy: Policy
    history: pd.DataFrame  # Foundation's cost history
    prices: pd.DataFrame  # monthly metal prices
    find_customer: Callable[[str], dict[str, str] | None]  # email domain -> customer
    clock: Clock


def next_number(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]) + 1


def submit_rfq(conn: sqlite3.Connection, sender: str, subject: str, body: str, clock: Clock) -> str:
    """Record an incoming email and queue its processing; return the run id."""
    with transaction(conn):
        n = next_number(conn)
        run_id = f"R-{n:04d}"
        append(
            conn,
            [
                NewEvent(
                    stream=f"run:{run_id}",
                    type="email.received",
                    actor="system:inbox",
                    run_id=run_id,
                    sim_at=clock.now(),
                    payload={
                        "message_id": f"msg-{n:04d}",
                        "sender": sender,
                        "subject": subject,
                        "body": body,
                    },
                )
            ],
        )
        jobs.enqueue(conn, "rfq", {"run_id": run_id}, key=run_id)
    return run_id


def step(
    conn: sqlite3.Connection,
    run_id: str,
    name: str,
    ok: bool,
    detail: str,
    started: float,
    clock: Clock,
) -> None:
    with transaction(conn):
        append(
            conn,
            [
                NewEvent(
                    stream=f"run:{run_id}",
                    type="step.finished",
                    actor="agent:quote",
                    run_id=run_id,
                    sim_at=clock.now(),
                    payload={
                        "step": name,
                        "ok": ok,
                        "detail": detail,
                        "seconds": round(time.perf_counter() - started, 3),
                    },
                )
            ],
        )


def finish(conn: sqlite3.Connection, run_id: str, status: str, clock: Clock) -> None:
    with transaction(conn):
        append(
            conn,
            [
                NewEvent(
                    stream=f"run:{run_id}",
                    type="run.finished",
                    actor="agent:quote",
                    run_id=run_id,
                    sim_at=clock.now(),
                    payload={"status": status},
                )
            ],
        )


def process_rfq(conn: sqlite3.Connection, run_id: str, deps: Deps) -> str:
    """Extract, screen, price, draft and route one RFQ; return the run's final status."""
    email = read_stream(conn, f"run:{run_id}")[0].payload
    clock = deps.clock

    t = time.perf_counter()
    try:
        extraction = extract(deps.llm, email["body"])
    except ExtractionError as exc:
        step(conn, run_id, "extract", False, str(exc)[:300], t, clock)
        finish(conn, run_id, "failed", clock)
        return "failed"
    lines = extraction.request.lines
    step(
        conn,
        run_id,
        "extract",
        True,
        f"{len(lines)} line(s), {extraction.attempts} attempt(s) with {deps.llm.name}",
        t,
        clock,
    )

    t = time.perf_counter()
    domain = email["sender"].rsplit("@", 1)[-1].strip(">").lower()
    found = deps.find_customer(domain)
    customer = Customer(**found) if found else UNKNOWN
    flags = screen(email["sender"], email["body"], found["email_domain"] if found else None)
    step(conn, run_id, "screen", True, f"customer {customer.name}; {len(flags)} flag(s)", t, clock)

    t = time.perf_counter()
    today = clock.now().date()
    priced: list[PricedLine] = [
        price_line(line, deps.history, deps.prices, today.strftime("%Y-%m")) for line in lines
    ]
    step(conn, run_id, "price", True, priced[0].method, t, clock)

    t = time.perf_counter()
    quote_id = run_id.replace("R-", "Q-")
    drafted, decided = draft(
        quote_id, customer, priced, flags, deps.policy, date.fromisoformat(str(today))
    )
    with transaction(conn):
        append(
            conn,
            [
                NewEvent(
                    stream=f"quote:{quote_id}",
                    type="quote.drafted",
                    actor="agent:quote",
                    run_id=run_id,
                    sim_at=clock.now(),
                    payload=drafted,
                ),
                NewEvent(
                    stream=f"quote:{quote_id}",
                    type="policy.decided",
                    actor="agent:quote",
                    run_id=run_id,
                    sim_at=clock.now(),
                    payload=decided,
                ),
            ],
        )
    step(conn, run_id, "draft", True, f"{quote_id}: {decided['bucket']}", t, clock)
    status = "flagged" if decided["bucket"] == "flagged" else "inbox"
    finish(conn, run_id, status, clock)
    return status
