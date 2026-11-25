"""End to end with the fake model: email -> run -> inbox -> approval -> outbox."""

from datetime import datetime

import pandas as pd
import pytest

from quote_desk.core.clock import FixedClock
from quote_desk.intake.llm import FakeLLM
from quote_desk.services import inbox
from quote_desk.services.rfq import Deps, submit_rfq
from quote_desk.services.worker import load_default_policy, run_once
from quote_desk.storage import projections
from quote_desk.storage.db import connect
from quote_desk.storage.events import ConcurrencyError, verify_chain

CUSTOMER = {
    "customer_id": "C1",
    "name": "Acme",
    "segment": "utility",
    "email_domain": "acme.com",
    "contact_email": "buyer@acme.com",
}
JOBS = [
    (75, "copper", 9000),
    (150, "copper", 14000),
    (75, "aluminum", 7000),
    (500, "copper", 40000),
]
PRICES = pd.DataFrame(
    {"month": ["2025-01", "2026-11"], "metal": ["copper", "copper"], "usd_per_kg": [9.0, 13.5]}
)


def history() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "job_id": f"J{i}",
            "product_family": "transformer",
            "kva": kva,
            "winding": winding,
            "quote_date": "2025-01-15",
            "actual_unit_cost": cost,
            "actual_material_cost": cost * 0.5,
            "is_outlier": 0,
            "description": f"XFMR {kva}KVA {winding}",
        }
        for i, (kva, winding, cost) in enumerate(JOBS)
    )


@pytest.fixture
def setup(tmp_path):
    conn = connect(tmp_path / "app.sqlite")
    deps = Deps(
        llm=FakeLLM(),
        policy=load_default_policy(),
        history=history(),
        prices=PRICES,
        find_customer=lambda d: CUSTOMER if d == "acme.com" else None,
        clock=FixedClock(datetime(2026, 11, 20, 9)),
    )
    return conn, deps


def only_item(conn):
    (item,) = inbox.inbox(conn)
    return item


def test_email_becomes_a_ready_draft_then_an_approved_staged_reply(setup):
    conn, deps = setup
    run_id = submit_rfq(conn, "buyer@acme.com", "RFQ", "2 x 75 kva copper transformer", deps.clock)
    assert run_once(conn, deps) and not run_once(conn, deps)
    item = only_item(conn)
    assert item["bucket"] == "ready" and item["run_id"] == run_id
    steps = [r["step"] for r in conn.execute("SELECT step FROM run_steps ORDER BY position")]
    assert steps == ["extract", "screen", "price", "draft"]
    # 9000 bought at copper 9.0; its material half rises 50% at 13.5 -> 11250
    view = conn.execute("SELECT data FROM quote_view").fetchone()[0]
    assert '"unit_cost": 11250.0' in view

    version = inbox.version(conn, item["quote_id"])
    inbox.decide_quote(
        conn,
        item["quote_id"],
        "approved",
        "estimator",
        deps.policy,
        deps.clock,
        expected_version=version,
    )
    (staged,) = inbox.outbox(conn)
    assert staged["recipient"] == "buyer@acme.com" and "Acme" in staged["body"]
    assert verify_chain(conn) is None
    live = projections.dump(conn)
    projections.rebuild(conn)
    assert projections.dump(conn) == live


def test_payment_change_email_is_flagged_and_cannot_be_approved(setup):
    conn, deps = setup
    body = "75 kva transformer\nOur bank details have changed"
    submit_rfq(conn, "buyer@acme.com", "Urgent", body, deps.clock)
    run_once(conn, deps)
    item = only_item(conn)
    assert item["bucket"] == "flagged" and item["rule_ids"] == ["R-WARNING"]
    for role in ("estimator", "senior"):
        with pytest.raises(inbox.NotAllowed):
            inbox.decide_quote(conn, item["quote_id"], "approved", role, deps.policy, deps.clock)
    assert inbox.outbox(conn) == []


def test_estimator_cannot_approve_what_needs_a_senior(setup):
    conn, deps = setup
    submit_rfq(conn, "buyer@acme.com", "Big", "20 x 500 kva copper transformer", deps.clock)
    run_once(conn, deps)
    item = only_item(conn)
    assert item["bucket"] == "needs_senior"
    with pytest.raises(inbox.NotAllowed):
        inbox.decide_quote(conn, item["quote_id"], "approved", "estimator", deps.policy, deps.clock)
    inbox.decide_quote(conn, item["quote_id"], "approved", "senior", deps.policy, deps.clock)
    assert len(inbox.outbox(conn)) == 1


def test_a_stale_screen_cannot_overwrite_a_newer_decision(setup):
    conn, deps = setup
    submit_rfq(conn, "buyer@acme.com", "RFQ", "75 kva copper transformer", deps.clock)
    run_once(conn, deps)
    quote_id = only_item(conn)["quote_id"]
    seen = inbox.version(conn, quote_id)
    inbox.decide_quote(
        conn, quote_id, "rejected", "estimator", deps.policy, deps.clock, expected_version=seen
    )
    with pytest.raises(ConcurrencyError):
        inbox.decide_quote(
            conn, quote_id, "approved", "estimator", deps.policy, deps.clock, expected_version=seen
        )
    assert inbox.outbox(conn) == []


def test_unknown_sender_is_flagged(setup):
    conn, deps = setup
    submit_rfq(conn, "x@lookalike-acme.com", "RFQ", "75 kva copper transformer", deps.clock)
    run_once(conn, deps)
    assert only_item(conn)["bucket"] == "flagged"
