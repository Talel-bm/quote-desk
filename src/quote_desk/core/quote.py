"""Shared quote data shapes, used by intake, forge and workforce alike.

They live in `core` because those three layers may not import each other (ADR 2):
intake produces an `RFQRequest`, forge turns each line into a `PricedLine`, and
workforce drafts a quote from both.
"""

from typing import Any

from pydantic import BaseModel, Field


class RFQLine(BaseModel):
    """One product the customer asks about."""

    family: str  # a key of products.families.FAMILIES
    quantity: int = Field(ge=1)
    config: dict[str, Any]  # validated against the family's config model


class RFQRequest(BaseModel):
    """What a customer asked for, as extracted from their message."""

    lines: list[RFQLine] = Field(min_length=1)
    requested_ship_date: str | None = None
    notes: str | None = None


class Customer(BaseModel):
    customer_id: str
    name: str
    segment: str
    email_domain: str
    contact_email: str


class SimilarJob(BaseModel):
    job_id: str
    description: str
    quote_date: str
    actual_unit_cost: float  # what it really cost then
    adjusted_unit_cost: float  # the same job at today's metal price


class PricedLine(BaseModel):
    """Forge's answer for one line: an estimated unit cost and where it came from."""

    family: str
    quantity: int
    config: dict[str, Any]
    unit_cost: float
    method: str  # e.g. "baseline: similar job x copper"
    similar: list[SimilarJob] = []
