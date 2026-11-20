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
    return {csv.stem: read_csv(csv) for csv in sorted(Path(folder).glob("*.csv"))}


SQLITE_SUFFIXES = {".sqlite", ".sqlite3", ".db"}


def read_csv(path: Path) -> pd.DataFrame:
    """Read one CSV as text; only truly empty cells count as missing."""
    return pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""])


def load_source(path) -> dict[str, pd.DataFrame]:
    """Load any supported source: a folder of CSVs, one CSV, or a SQLite file."""
    path = Path(path)
    if path.is_dir():
        tables = load_csv_folder(path)
    elif path.suffix.lower() == ".csv":
        tables = {path.stem: read_csv(path)}
    elif path.suffix.lower() in SQLITE_SUFFIXES:
        tables = load_sqlite(path)
    else:
        raise ValueError(f"{path}: expected a folder of CSVs, a .csv file or a SQLite file")
    if not tables:
        raise ValueError(f"{path}: no tables found")
    return tables
