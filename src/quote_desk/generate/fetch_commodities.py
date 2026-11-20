"""One-time download of real monthly metal prices from the World Bank Pink Sheet.

Run with `uv run quote-desk fetch-commodities`. The result is a small CSV that is
committed to the repo, so generating data later never needs the internet.
"""

import io

import httpx
import pandas as pd

from quote_desk import config

PINK_SHEET_URL = (
    "https://thedocs.worldbank.org/en/doc/74e8be41ceb20fa0da750cda2f6b9e4e-0050012026/"
    "related/CMO-Historical-Data-Monthly.xlsx"
)
RAW_CSV = config.ROOT / "data" / "raw" / "commodity_prices_worldbank.csv"

# First and last month of the history window (36 months).
START_MONTH = "2023-11"
END_MONTH = "2026-10"

# Pink Sheet column name -> our column name.
COLUMNS = {
    "Copper": "copper_usd_per_mt",
    "Aluminum": "aluminum_usd_per_mt",
    "Iron ore, cfr spot": "iron_ore_usd_per_dmtu",
}


def parse_pink_sheet(raw: pd.DataFrame) -> pd.DataFrame:
    """Turn the raw 'Monthly Prices' sheet into a tidy table of our three metals.

    The sheet has a few title rows, then a row of commodity names, then a row of
    units, then one row per month labelled like '2026M10'.
    """
    # Find the header row: the one that contains the word "Copper".
    header_idx = raw.index[raw.eq("Copper").any(axis=1)][0]
    header = raw.loc[header_idx]

    # Keep only rows whose first cell looks like a month label, e.g. "2026M10".
    is_month = raw[0].astype(str).str.fullmatch(r"\d{4}M\d{2}")
    data = raw[is_month]

    out = pd.DataFrame({"month": data[0].map(lambda s: f"{s[:4]}-{s[5:]}")})
    for sheet_name, our_name in COLUMNS.items():
        col = header.index[header == sheet_name][0]
        out[our_name] = pd.to_numeric(data[col])
    return out.reset_index(drop=True)


def select_window(prices: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    """Keep only the months between start and end (inclusive), e.g. '2023-11'."""
    mask = (prices["month"] >= start) & (prices["month"] <= end)
    window = prices[mask].reset_index(drop=True)
    if window.isna().any().any():
        raise ValueError("Pink Sheet has missing values in the selected window")
    return window


def fetch() -> pd.DataFrame:
    """Download the Pink Sheet, extract our metals for the window, save the CSV."""
    response = httpx.get(PINK_SHEET_URL, follow_redirects=True, timeout=60)
    response.raise_for_status()
    raw = pd.read_excel(io.BytesIO(response.content), sheet_name="Monthly Prices", header=None)
    prices = select_window(parse_pink_sheet(raw), START_MONTH, END_MONTH)
    RAW_CSV.parent.mkdir(parents=True, exist_ok=True)
    prices.to_csv(RAW_CSV, index=False)
    print(f"Wrote {len(prices)} months to {RAW_CSV.relative_to(config.ROOT)}")
    return prices
