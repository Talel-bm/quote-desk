"""The quote agent (v0): turn priced lines into a draft quote, a reply and a policy decision.

Pure function: no database, no model call. The reply is built from a template and
approved fields only; it never contains costs or margins, and the raw customer email is
not an input here at all (ADR 8).
"""

from datetime import date, timedelta
from typing import Any

from quote_desk.core.quote import Customer, PricedLine
from quote_desk.products.families import FAMILIES, missing_options
from quote_desk.workforce.policy import Policy, bucket, target_margin


def unit_price(cost: float, margin: float) -> float:
    """Price such that (price - cost) / price = margin."""
    return round(cost / (1 - margin), 2)


def margin_of(lines: list[dict[str, Any]], total: float) -> float:
    """Quoted margin, (price - cost) / price, rounded to 4 decimals.

    Rounding matters: prices are rounded to cents, so a quote priced exactly at an 18%
    target can come out at 17.9999% and wrongly trip an "under 18%" rule.
    """
    cost = sum(line["qty"] * line["unit_cost"] for line in lines)
    return round((total - cost) / total, 4) if total else 0.0


def describe(line: PricedLine) -> str:
    options = ", ".join(f"{k} {v}" for k, v in line.config.items() if v is not None)
    return f"{line.family} ({options})" if options else line.family


def reply_text(customer: Customer, lines: list[dict[str, Any]], valid_until: date) -> str:
    rows = [
        f"- {line['description']}: {line['qty']} x ${line['unit_price']:,.2f}"
        f" = ${line['qty'] * line['unit_price']:,.2f}"
        for line in lines
    ]
    questions = [
        f"- {line['description']}: please confirm {', '.join(line['missing'])}"
        for line in lines
        if line["missing"]
    ]
    text = [f"Hello {customer.name},", "", "Thank you for your request. Our quotation:", *rows]
    if questions:
        text += ["", "To finalize, could you confirm the following:", *questions]
    text += [
        "",
        f"Prices are valid until {valid_until.isoformat()}.",
        "",
        "Best regards,",
        "Lakeshore Group quote desk",
    ]
    return "\n".join(text)


def draft(
    quote_id: str,
    customer: Customer,
    priced: list[PricedLine],
    flags: list[str],
    policy: Policy,
    today: date,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the `quote.drafted` and `policy.decided` payloads for one RFQ."""
    margin = target_margin(policy, customer.segment)
    lines: list[dict[str, Any]] = []
    for line in priced:
        options = FAMILIES[line.family].model_validate(line.config)
        lines.append(
            {
                "family": line.family,
                "qty": line.quantity,
                "config": line.config,
                "description": describe(line),
                "unit_cost": round(line.unit_cost, 2),
                "unit_price": unit_price(line.unit_cost, margin),
                "missing": missing_options(line.family, options),
                "method": line.method,
                "similar": [s.model_dump() for s in line.similar],
            }
        )
    total = round(sum(line["qty"] * line["unit_price"] for line in lines), 2)
    valid_until = today + timedelta(days=policy.pricing.validity_days)
    drafted = {
        "quote_id": quote_id,
        "customer": customer.name,
        "recipient": customer.contact_email,
        "lines": lines,
        "total": total,
        "reply": reply_text(customer, lines, valid_until),
    }
    context = {
        "margin": margin_of(lines, total),
        "total": total,
        "flag_count": len(flags),
    }
    where, decision = bucket(policy, context)
    decided = {
        "quote_id": quote_id,
        "bucket": where,
        "rule_ids": decision.forbids or decision.permits,
        "reasons": decision.reasons,
        "flags": flags,
        "policy_version": policy.version,
    }
    return drafted, decided
