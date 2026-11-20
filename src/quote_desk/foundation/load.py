"""Read the raw source tables, without ever changing them."""

import sqlite3
from pathlib import Path

import pandas as pd


def load_sqlite(path: Path) -> dict[str, pd.DataFrame]:
    """Read every table of a SQLite file into DataFrames.

    The file is opened read-only (`mode=ro`), so Foundation can never modify
    the source system, the same access a real ERP integration should get.
    """
    if not Path(path).exists():
        raise FileNotFoundError(f"{path} not found. Run `uv run quote-desk generate` first.")
    uri = f"file:{Path(path).as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        names = [
            row[0]
            for row in conn.execute(
                "select name from sqlite_master where type = 'table' order by name"
            )
        ]
        return {name: pd.read_sql_query(f'select * from "{name}"', conn) for name in names}


def load_csv_folder(folder: Path) -> dict[str, pd.DataFrame]:
    """Read every CSV in a folder; the file name (without .csv) is the table name."""
    return {
        csv.stem: pd.read_csv(csv, dtype=str, keep_default_na=False, na_values=[""])
        for csv in sorted(Path(folder).glob("*.csv"))
    }
