"""Guardrail flags: things the system must point out to a human and never act on.

Flags never stop the email from being read; they route the result to "Flagged". They
are a warning light, not the defense: the defense is that no model output can change
recipients, prices or bank details (ADR 8).
"""

import re

PAYMENT_CHANGE = re.compile(
    r"(bank|banking|account|wire|remit|payment)\s+(details|information|info|instructions)"
    r".{0,40}(changed|change|new|updated|update)|new\s+(bank|account)",
    re.I | re.S,
)
INSTRUCTIONS_TO_AI = re.compile(
    r"ignore (all |your |any )?(previous |prior )?(instructions|rules)"
    r"|you are (now )?an? (ai|assistant)|system prompt|approve (this|the) quote automatically",
    re.I,
)


def screen(sender: str, body: str, customer_domain: str | None) -> list[str]:
    """Return the list of flags raised by this message (empty if none)."""
    flags = []
    if PAYMENT_CHANGE.search(body):
        flags.append("payment-detail change requested: verify by phone using the number on file")
    if INSTRUCTIONS_TO_AI.search(body):
        flags.append("message contains instructions aimed at the AI")
    domain = sender.rsplit("@", 1)[-1].lower().strip(">")
    if customer_domain is None:
        flags.append(f"unknown sender domain {domain!r}: no customer on file")
    elif domain != customer_domain.lower():
        flags.append(f"sender domain {domain!r} does not match customer domain {customer_domain!r}")
    return flags
