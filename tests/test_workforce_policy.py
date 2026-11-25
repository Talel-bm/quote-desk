"""Authority policy (workforce/policy.py) and the quote agent (workforce/quote.py)."""

from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from quote_desk import config
from quote_desk.core.quote import Customer, PricedLine
from quote_desk.services.worker import load_default_policy
from quote_desk.workforce.policy import Principal, bucket, decide
from quote_desk.workforce.quote import draft, unit_price

POLICY = load_default_policy()
SEND = "quote.approve_send"
ESTIMATOR = Principal(kind="human", role="estimator")
AGENT = Principal(kind="agent", role="quote")
OK = {"margin": 0.22, "total": 10_000, "flag_count": 0}


def test_every_rule_cites_a_memo_section():
    memo = (config.ROOT / POLICY.source_doc).read_text(encoding="utf-8")
    for rule in POLICY.rules:
        assert f"{rule.source} " in memo, rule.id


def test_buckets():
    assert bucket(POLICY, OK)[0] == "ready"
    assert bucket(POLICY, OK | {"margin": 0.15})[0] == "needs_senior"
    assert bucket(POLICY, OK | {"total": 300_000})[0] == "needs_senior"
    where, why = bucket(POLICY, OK | {"flag_count": 1})
    assert where == "flagged" and why.forbids == ["R-WARNING"]


def test_agents_can_never_approve_and_unknown_actions_are_denied():
    assert not decide(POLICY, AGENT, SEND, OK).allowed
    assert not decide(POLICY, ESTIMATOR, "quote.delete", OK).allowed  # default deny


@given(
    margin=st.floats(-1, 1),
    total=st.floats(0, 1e7),
    flags=st.integers(0, 3),
    role=st.sampled_from(["estimator", "senior", "intern"]),
    kind=st.sampled_from(["human", "agent"]),
)
def test_forbid_always_wins_and_permit_is_required(margin, total, flags, role, kind):
    ctx = {"margin": margin, "total": total, "flag_count": flags}
    d = decide(POLICY, Principal(kind=kind, role=role), SEND, ctx)
    assert d.allowed == (bool(d.permits) and not d.forbids)
    if flags or kind == "agent":
        assert not d.allowed


def test_unit_price_hits_the_target_margin():
    price = unit_price(100.0, 0.2)
    assert price == 125.0 and (price - 100) / price == pytest.approx(0.2)


def test_draft_reply_never_shows_cost_and_asks_for_missing_options():
    customer = Customer(
        customer_id="C1",
        name="Acme",
        segment="utility",
        email_domain="acme.com",
        contact_email="buyer@acme.com",
    )
    line = PricedLine(
        family="transformer", quantity=2, config={"kva": 75.0}, unit_cost=1234.5, method="test"
    )
    drafted, decided = draft("Q-1", customer, [line], [], POLICY, date(2026, 11, 20))
    assert drafted["recipient"] == "buyer@acme.com"
    assert "1,234.5" not in drafted["reply"] and "please confirm" in drafted["reply"]
    assert "2026-12-20" in drafted["reply"]  # 30-day validity
    assert decided["bucket"] == "ready" and decided["policy_version"] == "v1"


def test_a_quote_at_exactly_the_target_margin_is_not_below_it():  # never again
    customer = Customer(
        customer_id="C1",
        name="Acme",
        segment="distributor",  # target 18% = the senior threshold
        email_domain="acme.com",
        contact_email="buyer@acme.com",
    )
    lines = [
        PricedLine(family="enclosure", quantity=1, config={}, unit_cost=504.33, method="t"),
        PricedLine(family="transformer", quantity=4, config={}, unit_cost=2583.34, method="t"),
    ]
    _, decided = draft("Q-1", customer, lines, [], POLICY, date(2026, 11, 20))
    assert decided["bucket"] == "ready"
