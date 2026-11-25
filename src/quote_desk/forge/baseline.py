"""Forge v0: the baseline an estimator would use, made explicit.

"Take the most similar past job and adjust its cost to today's metal price." This is
the first rung of the baseline ladder (SPEC Step 6): every later model must beat it.

Adjustment: only the material part of a job's cost follows the metal price, so
    adjusted = cost x (1 + material_share x (price_today / price_then - 1))
where material_share = actual material cost / actual unit cost of that job, and the
metal is the job's winding (copper or aluminum). Enclosures are not adjusted (their
steel has no index in this version).
"""

import math
from typing import Any

import pandas as pd

from quote_desk.core.quote import PricedLine, RFQLine, SimilarJob

MISMATCH_PENALTY = 0.5  # distance added per option that differs from the request


def price_on(prices: pd.DataFrame, metal: str, month: str) -> float | None:
    """The metal's price in the latest month at or before `month` (YYYY-MM)."""
    rows = prices[(prices["metal"] == metal) & (prices["month"] <= month)]
    return None if rows.empty else float(rows.sort_values("month")["usd_per_kg"].iloc[-1])


def distance(request: dict[str, Any], job: pd.Series) -> float:
    """How different a past job is from the request: size gap plus option mismatches.

    Size is compared on a log scale (75 vs 112.5 kVA is as far as 500 vs 750). Options
    the customer did not state are ignored, since any value would do.
    """
    d = 0.0
    for option, wanted in request.items():
        if wanted is None or option not in job.index:
            continue
        if option == "kva":
            d += abs(math.log(float(wanted)) - math.log(float(job["kva"])))
        elif str(job[option]) != str(wanted):
            d += MISMATCH_PENALTY
    return d


def adjusted_cost(job: pd.Series, prices: pd.DataFrame, today: str) -> float:
    """A past job's unit cost moved to today's metal price (unchanged if no metal index)."""
    cost = float(job["actual_unit_cost"])
    metal = job.get("winding")
    if metal not in ("copper", "aluminum"):
        return cost
    then = price_on(prices, metal, str(job["quote_date"])[:7])
    now = price_on(prices, metal, today)
    if not then or not now:
        return cost
    share = float(job["actual_material_cost"]) / cost
    return cost * (1 + share * (now / then - 1))


def price_line(
    line: RFQLine, history: pd.DataFrame, prices: pd.DataFrame, today: str, k: int = 3
) -> PricedLine:
    """Estimate one line's unit cost from the most similar past job of the same family."""
    jobs = history[(history["product_family"] == line.family) & ~history["is_outlier"].astype(bool)]
    jobs = jobs.dropna(subset=["actual_unit_cost", "actual_material_cost"])
    if jobs.empty:
        raise ValueError(f"no past jobs for family {line.family!r}")
    scored = jobs.assign(distance=[distance(line.config, job) for _, job in jobs.iterrows()])
    nearest = scored.sort_values(["distance", "quote_date"], ascending=[True, False]).head(k)
    similar = [
        SimilarJob(
            job_id=str(job["job_id"]),
            description=str(job["description"]),
            quote_date=str(job["quote_date"]),
            actual_unit_cost=round(float(job["actual_unit_cost"]), 2),
            adjusted_unit_cost=round(adjusted_cost(job, prices, today), 2),
        )
        for _, job in nearest.iterrows()
    ]
    return PricedLine(
        family=line.family,
        quantity=line.quantity,
        config=line.config,
        unit_cost=similar[0].adjusted_unit_cost,
        method="baseline: most similar past job, adjusted to today's metal price",
        similar=similar,
    )
