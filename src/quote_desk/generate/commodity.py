"""Monthly metal prices in US$ per kg, used to cost every job.

Copper and aluminum are real World Bank prices (see data/raw/README.md).
Electrical steel has no free public series, so it is synthetic: a seeded series
that loosely follows real iron-ore moves.
"""

import numpy as np
import pandas as pd

from quote_desk import config
from quote_desk.generate.fetch_commodities import RAW_CSV

METALS = ["copper", "aluminum", "electrical_steel"]

# Electrical steel starting price (US$/kg) and how strongly it follows iron ore.
ESTEEL_BASE = 2.60
ESTEEL_ORE_ELASTICITY = 0.5  # +10% iron ore -> about +5% electrical steel
ESTEEL_NOISE = 0.02  # size of the month-to-month random wiggle
ESTEEL_PERSISTENCE = 0.7  # how much of last month's wiggle carries over


def synthetic_electrical_steel(iron_ore: pd.Series, seed: int) -> np.ndarray:
    """Build the electrical-steel price series ($/kg) from iron ore plus seeded noise."""
    rng = np.random.default_rng(seed)
    ore_ratio = (iron_ore / iron_ore.iloc[0]).to_numpy()
    wiggle = np.zeros(len(ore_ratio))
    for i in range(1, len(wiggle)):
        wiggle[i] = ESTEEL_PERSISTENCE * wiggle[i - 1] + rng.normal(0, ESTEEL_NOISE)
    return ESTEEL_BASE * ore_ratio**ESTEEL_ORE_ELASTICITY * np.exp(wiggle)


def load_prices(seed: int = config.SEED) -> pd.DataFrame:
    """Return one row per month: month, copper, aluminum, electrical_steel ($/kg)."""
    raw = pd.read_csv(RAW_CSV, dtype={"month": str})
    return pd.DataFrame(
        {
            "month": raw["month"],
            "copper": raw["copper_usd_per_mt"] / 1000,
            "aluminum": raw["aluminum_usd_per_mt"] / 1000,
            "electrical_steel": synthetic_electrical_steel(raw["iron_ore_usd_per_dmtu"], seed),
        }
    )


def prices_on(prices: pd.DataFrame, date) -> dict[str, float]:
    """Prices for the month of `date`. After the last month, the last known prices apply."""
    month = pd.Timestamp(date).strftime("%Y-%m")
    known = prices[prices["month"] <= month]
    if known.empty:
        raise ValueError(f"No prices before {month}")
    row = known.iloc[-1]
    return {metal: float(row[metal]) for metal in METALS}


def price_on(prices: pd.DataFrame, date, metal: str) -> float:
    """Price of one metal ($/kg) for the month of `date`."""
    return prices_on(prices, date)[metal]


def to_erp_table(prices: pd.DataFrame) -> pd.DataFrame:
    """Long format for the ERP: one row per month and metal, with where it came from."""
    long = prices.melt(id_vars="month", var_name="metal", value_name="usd_per_kg")
    long["source"] = np.where(long["metal"] == "electrical_steel", "synthetic", "worldbank")
    long["usd_per_kg"] = long["usd_per_kg"].round(4)
    return long.sort_values(["month", "metal"]).reset_index(drop=True)
