"""Event types: the facts the app records, one per thing that happened.

Every change in the app is an event appended to one log (ADR 5): an email arrived, an
RFQ was extracted, a quote was drafted, a human approved it. Screens are built from
these events, so the log is the single source of truth.

Each event type has a Pydantic payload model, registered in `PAYLOADS`. Appending an
event of an unknown type, or with a payload that doesn't match its model, fails.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class NewEvent(BaseModel):
    """An event before it is stored: what the caller decides."""

    model_config = ConfigDict(frozen=True)

    stream: str  # what it is about, e.g. "quote:Q-0001", "run:R-0001", "policy"
    type: str  # e.g. "quote.drafted"; must be a key of PAYLOADS
    actor: str  # who did it: "agent:quote", "user:estimator", "system:clock"
    payload: dict[str, Any]
    run_id: str | None = None  # which workflow run it belongs to
    causation: int | None = None  # position of the event that caused it
    sim_at: datetime  # simulated (business) time


class StoredEvent(NewEvent):
    """An event as stored in the log, with its place in the chain."""

    position: int  # global order, starting at 1
    stream_seq: int  # order within its stream, starting at 1
    wall_at: datetime  # real time it was written
    schema_v: int
    prev_hash: str
    hash: str


# --- Payloads -----------------------------------------------------------------
class EmailReceived(BaseModel):
    message_id: str
    sender: str
    subject: str
    body: str


class StepFinished(BaseModel):
    step: str  # "extract", "price", "policy", "draft"
    ok: bool
    detail: str = ""
    seconds: float = 0.0


class RunFinished(BaseModel):
    status: str  # "inbox" | "flagged" | "failed"


class QuoteDrafted(BaseModel):
    quote_id: str
    customer: str
    recipient: str  # from the customer record on file, never from the email
    lines: list[dict[str, Any]]  # family, config, qty, unit cost, unit price
    total: float
    reply: str  # draft reply email


class PolicyDecided(BaseModel):
    quote_id: str
    bucket: str  # "ready" | "needs_senior" | "flagged"
    rule_ids: list[str]
    reasons: list[str]  # why the policy decided this (rule reason + memo section)
    flags: list[str] = []  # guardrail warnings raised by intake
    policy_version: str


class QuoteDecided(BaseModel):
    """A human decision on a quote: approve, reject or edit."""

    quote_id: str
    decision: str  # "approved" | "rejected"
    reason: str = ""


class EmailStaged(BaseModel):
    """An approved email placed in the outbox."""

    quote_id: str
    recipient: str
    approval_position: int


PAYLOADS: dict[str, type[BaseModel]] = {
    "email.received": EmailReceived,
    "step.finished": StepFinished,
    "run.finished": RunFinished,
    "quote.drafted": QuoteDrafted,
    "policy.decided": PolicyDecided,
    "quote.decided": QuoteDecided,
    "email.staged": EmailStaged,
}


def validate_payload(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Check a payload against its event type's model; return it normalized."""
    if event_type not in PAYLOADS:
        raise ValueError(f"unknown event type: {event_type}")
    return PAYLOADS[event_type].model_validate(payload).model_dump(mode="json")
