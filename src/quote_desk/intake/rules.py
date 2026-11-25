"""A no-LLM extractor built from regular expressions.

It serves two purposes: it is the keyless "fake" model behind the public demo and the
tests, and it is the `rules` baseline every LLM must beat in Step 7. It understands the
common shorthand estimators see ("75kva 3ph 600-208/120 alum NEMA3R, qty 4").
"""

import json
import re
from typing import Any

KVA = re.compile(r"(\d+(?:\.\d+)?)\s*-?\s*kva", re.I)
QTY = re.compile(
    r"(?:qty|quantity)\s*[:=]?\s*(\d+)"
    r"|(\d+)\s*(?:units?|pcs|pieces|x\b|enclosures?|transformers?|xfmrs?|cabinets?)"
    r"|\bx\s*(\d+)",
    re.I,
)
PHASE = re.compile(r"\b([13])\s*-?\s*(?:ph|phase)\b", re.I)
VOLTAGES = re.compile(r"\b(480|600|4160)\s*v?\s*(?:-|to|/|\s)\s*(208/120|480/277|600/347)", re.I)
NEMA = re.compile(r"nema\s*-?\s*(1|3r|4|12)\b", re.I)
SIZE = re.compile(r"\b(\d{2})\s*x\s*(\d{2})\s*x\s*(\d{1,2})\b", re.I)
GAUGE = re.compile(r"\b(12|14|16)\s*(?:ga|gauge)\b", re.I)
K_FACTOR = re.compile(r"\bk\s*-?\s*(1|4|13)\b", re.I)


def first(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return next((g for g in match.groups() if g), None) if match else None


def winding(text: str) -> str | None:
    if re.search(r"\b(alum|aluminum|aluminium|al)\b", text, re.I):
        return "aluminum"
    if re.search(r"\b(copper|cu)\b", text, re.I):
        return "copper"
    return None


def nema(text: str) -> str | None:
    value = first(NEMA, text)
    return f"NEMA {value.upper()}" if value else None


def transformer_line(text: str) -> dict[str, Any]:
    volts = VOLTAGES.search(text)
    k = first(K_FACTOR, text)
    phase = first(PHASE, text)
    kva = first(KVA, text)
    return {
        "family": "transformer",
        "quantity": int(first(QTY, text) or 1),
        "config": {
            "kva": float(kva) if kva else None,
            "primary_v": int(volts.group(1)) if volts else None,
            "secondary_v": volts.group(2) if volts else None,
            "phase": int(phase) if phase else None,
            "winding": winding(text),
            "k_factor": int(k) if k else None,
            "enclosure": nema(text),
            "efficiency": "premium" if re.search(r"premium", text, re.I) else None,
        },
    }


def enclosure_line(text: str) -> dict[str, Any]:
    size = SIZE.search(text)
    gauge = first(GAUGE, text)
    finish = next(
        (f for f in ("powder white", "powder gray", "galvanized") if f in text.lower()), None
    )
    return {
        "family": "enclosure",
        "quantity": int(first(QTY, text) or 1),
        "config": {
            "size": "x".join(size.groups()) if size else None,
            "gauge": int(gauge) if gauge else None,
            "finish": finish,
            "nema_rating": nema(text),
        },
    }


def extract_lines(body: str) -> list[dict[str, Any]]:
    """One RFQ line per text line that names a transformer (kVA) or an enclosure."""
    lines = []
    for text in body.splitlines():
        if KVA.search(text) or re.search(r"transformer|xfmr", text, re.I):
            lines.append(transformer_line(text))
        elif re.search(r"enclosure|cabinet|\bbox\b", text, re.I):
            lines.append(enclosure_line(text))
    return lines


def rules_extract(body: str) -> str:
    """Return the extraction as JSON text, exactly like an LLM would."""
    return json.dumps({"lines": extract_lines(body)})
