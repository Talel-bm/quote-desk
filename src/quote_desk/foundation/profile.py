"""Profile raw tables with no contract: what is actually in the data?

This is the first thing to run on a new source. It answers the questions an
engineer brings to the customer: which columns identify rows, which columns
look like links between tables, what types and value shapes appear, and how
much is missing. Nothing here knows about transformers or this ERP.
"""

import itertools
import re

import pandas as pd

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}( \d{2}:\d{2}:\d{2})?$")


def shape(value) -> str:
    """The 'shape' of a code: letters -> A, digits -> 9, runs collapsed.

    'TX-75-3P-480' -> 'A-9-9A-9' and 'L40001' -> 'A9', so two numbering
    schemes for the same kind of thing show up as different shapes.
    """
    s = re.sub(r"[A-Za-z]+", "A", str(value))
    return re.sub(r"\d+", "9", s)


def guess_type(series: pd.Series) -> str:
    """Guess a column's type from its non-empty values: int, float, date or text."""
    values = series.dropna()
    if values.empty:
        return "empty"
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().all():
        return "int" if (numeric == numeric.round()).all() else "float"
    if values.astype(str).str.match(DATE_RE).all():
        return "date"
    return "text"


def profile_columns(df: pd.DataFrame) -> pd.DataFrame:
    """One row per column: type, % missing, distinct values, examples, range, shapes."""
    rows = []
    for col in df.columns:
        s = df[col]
        kind = guess_type(s)
        values = s.dropna()
        row = {
            "column": col,
            "type": kind,
            "missing_pct": round(s.isna().mean() * 100, 1),
            "distinct": int(values.nunique()),
            "top_values": ", ".join(map(str, values.value_counts().head(3).index)),
            "min": None,
            "max": None,
            "shapes": None,
        }
        if kind in ("int", "float", "date") and not values.empty:
            ordered = pd.to_numeric(values) if kind != "date" else values.astype(str)
            row["min"], row["max"] = str(ordered.min()), str(ordered.max())
        if kind == "text":
            counts = values.map(shape).value_counts()
            row["shapes"] = ", ".join(f"{p} ({n})" for p, n in counts.head(5).items())
        rows.append(row)
    return pd.DataFrame(rows)


def candidate_keys(df: pd.DataFrame, max_size: int = 2) -> list[list[str]]:
    """Columns (or pairs of columns) whose values are never empty and never repeat.

    Only text and integer columns qualify: measured numbers and dates can be
    unique by coincidence without identifying anything. Single columns are
    tried first; pairs only if no single column works.
    """
    if df.empty:
        return []
    complete = [
        c for c in df.columns if df[c].notna().all() and guess_type(df[c]) in ("text", "int")
    ]
    singles = [[c] for c in complete if df[c].is_unique]
    if singles or max_size < 2:
        return singles
    return [
        list(pair)
        for pair in itertools.combinations(complete, 2)
        if not df.duplicated(subset=list(pair)).any()
    ]


def candidate_relationships(
    tables: dict[str, pd.DataFrame], min_containment: float = 0.5
) -> pd.DataFrame:
    """Columns that look like links: their values are mostly found in another
    table's single-column key.

    `containment` = share of the column's distinct values found in the key.
    100% means every link resolves; less means orphans (or a coincidence).
    """
    keys = {
        (name, key[0]): set(df[key[0]].astype(str))
        for name, df in tables.items()
        for key in candidate_keys(df, max_size=1)
        if guess_type(df[key[0]]) == "text"
    }
    rows = []
    for name, df in tables.items():
        for col in df.columns:
            if guess_type(df[col]) != "text":
                continue
            values = set(df[col].dropna().astype(str))
            if len(values) < 2:
                continue
            for (ref_table, ref_col), ref_values in keys.items():
                if (ref_table, ref_col) == (name, col):
                    continue
                containment = len(values & ref_values) / len(values)
                if containment >= min_containment:
                    rows.append(
                        {
                            "table": name,
                            "column": col,
                            "ref_table": ref_table,
                            "ref_column": ref_col,
                            "containment_pct": round(containment * 100, 1),
                        }
                    )
    return pd.DataFrame(
        rows, columns=["table", "column", "ref_table", "ref_column", "containment_pct"]
    )


def profile(tables: dict[str, pd.DataFrame]) -> dict:
    """Full profile of a source: per-table summary, per-column detail, keys, links."""
    summary = pd.DataFrame(
        [
            {
                "table": name,
                "rows": len(df),
                "columns": df.shape[1],
                "candidate_keys": "; ".join("+".join(k) for k in candidate_keys(df)) or "none",
            }
            for name, df in tables.items()
        ]
    )
    return {
        "summary": summary,
        "columns": {name: profile_columns(df) for name, df in tables.items()},
        "relationships": candidate_relationships(tables),
    }
