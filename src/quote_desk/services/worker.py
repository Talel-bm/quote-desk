"""The background worker: claims queued jobs one at a time and runs them.

One worker, by design (ADR 5): SQLite has one writer, and a single worker keeps the
order of events easy to reason about. The API starts it in a thread at startup.
"""

import sqlite3
import threading
from pathlib import Path

from quote_desk import config
from quote_desk.core.clock import SystemClock
from quote_desk.foundation import read
from quote_desk.intake.llm import FakeLLM, LLMClient
from quote_desk.services.rfq import Deps, process_rfq
from quote_desk.storage import jobs
from quote_desk.storage.db import connect, transaction
from quote_desk.workforce.policy import Policy, load_policy

POLICY_FILE = config.ROOT / "policy" / "authority.yaml"


def make_llm(provider: str) -> LLMClient:
    if provider == "fake":
        return FakeLLM()
    raise NotImplementedError(f"provider {provider!r} arrives in Step 7; use LLM_PROVIDER=fake")


def load_default_policy(path: Path = POLICY_FILE) -> Policy:
    return load_policy(path.read_text(encoding="utf-8"))


def default_deps() -> Deps:
    """Real dependencies: the configured model, the policy file, Foundation's data."""
    return Deps(
        llm=make_llm(config.LLM_PROVIDER),
        policy=load_default_policy(),
        history=read.cost_history(),
        prices=read.metal_prices(),
        find_customer=read.customer_by_domain,
        clock=SystemClock(),
    )


def run_once(conn: sqlite3.Connection, deps: Deps) -> bool:
    """Claim and run one job; return False if the queue was empty."""
    with transaction(conn):
        job = jobs.claim(conn)
    if job is None:
        return False
    try:
        if job["kind"] == "rfq":
            process_rfq(conn, job["payload"]["run_id"], deps)
        with transaction(conn):
            jobs.complete(conn, job["id"])
    except Exception as exc:  # recorded and retried; never kills the worker
        with transaction(conn):
            jobs.fail(conn, job["id"], f"{type(exc).__name__}: {exc}"[:500])
    return True


def run_forever(
    db_path: Path, deps: Deps, stop: threading.Event, idle_seconds: float = 0.2
) -> None:
    """Work until `stop` is set; sleep briefly when there is nothing to do."""
    conn = connect(db_path)
    while not stop.is_set():
        if not run_once(conn, deps):
            stop.wait(idle_seconds)
    conn.close()
