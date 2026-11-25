"""Read access to Foundation's cleaned data for the layers above it.

Forge and workforce read cleaned data only through here, never from the raw ERP. In
Step 5 this becomes `foundation/query.py` over the ontology.
"""

import sqlite3
from pathlib import Path

import pandas as pd

from quote_desk import config


def open_foundation(path: Path | None = None) -> sqlite3.Connection:
    """Open foundation.sqlite read-only."""
    db = path or config.FOUNDATION_DB
    if not Path(db).exists():
        raise FileNotFoundError(
            f"{db} not found: run `quote-desk generate` then `quote-desk clean`"
        )
    return sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True)


def cost_history(path: Path | None = None) -> pd.DataFrame:
    """Won, shipped jobs with their configuration and actual costs."""
    with open_foundation(path) as conn:
        return pd.read_sql("SELECT * FROM cost_history", conn)


def metal_prices(path: Path | None = None) -> pd.DataFrame:
    """Monthly metal prices in USD per kg (columns: month, metal, usd_per_kg)."""
    with open_foundation(path) as conn:
        return pd.read_sql("SELECT month, metal, usd_per_kg FROM commodity_prices", conn)


def customer_by_domain(domain: str, path: Path | None = None) -> dict[str, str] | None:
    """The customer whose email domain matches, or None if the sender is unknown."""
    with open_foundation(path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT customer_id, name, segment, email_domain, contact_email FROM customers"
            " WHERE lower(email_domain) = lower(?) LIMIT 1",
            (domain,),
        ).fetchone()
    return dict(row) if row else None
