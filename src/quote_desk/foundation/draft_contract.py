"""Draft a contract from the data alone, as a starting point for a person.

Guesses what patterns can reveal: each column's type, which column identifies
rows, and which columns link to other tables. It cannot guess business
meaning (which rows count, what a status means, when two records are the same
thing), so it leaves clearly marked TODOs for those.

The draft is written as a Python file so it can be read, edited and reviewed
like any other contract.
"""

import importlib.util
import re
import sys
from pathlib import Path

import pandas as pd

from quote_desk.foundation.contract import Contract
from quote_desk.foundation.profile import DATE_RE, candidate_keys, candidate_relationships

MOSTLY = 0.95  # share of values that must fit a type (or be unique) to propose it
LINK_MIN_SHARE = 0.7  # share of a column's values that must exist in another table's key
CATEGORY_MAX_DISTINCT = 20  # few distinct values -> a category, not free text
ALLOWED_VALUES_MAX = 10  # suggest listing the allowed values when there are this few


# --- Guesses ------------------------------------------------------------------
def draft_type(series: pd.Series) -> tuple[str, str | None]:
    """Guess a column type, tolerating a few bad values; return (type, note)."""
    values = series.dropna()
    if values.empty:
        return "str", "always empty"
    numbers = pd.to_numeric(values, errors="coerce")
    if numbers.notna().mean() >= MOSTLY:
        ok = numbers.dropna()
        kind = "int" if (ok == ok.round()).all() else "float"
        bad = int(numbers.isna().sum())
        return kind, f"{bad} value(s) are not numbers and will become missing" if bad else None
    is_date = values.astype(str).str.match(DATE_RE)
    if is_date.mean() >= MOSTLY:
        bad = int((~is_date).sum())
        return "date", f"{bad} value(s) are not dates and will become missing" if bad else None
    distinct = values.nunique()
    if distinct <= CATEGORY_MAX_DISTINCT and distinct < 0.5 * len(values):
        return "category", None
    return "str", None


def draft_key(df: pd.DataFrame) -> tuple[list[str], str]:
    """Guess the primary key: an exact key if one exists, else a nearly unique column."""
    exact = candidate_keys(df)
    if exact:
        return exact[0], "unique and never empty"
    best, best_share = None, 0.0
    for col in df.columns:
        values = df[col].dropna()
        if values.empty or df[col].isna().mean() > 0.01:
            continue
        share = values.nunique() / len(values)
        if share >= MOSTLY and share > best_share:
            best, best_share = col, share
    if best:
        repeats = int(df[best].duplicated().sum())
        return [best], f"{repeats} repeated value(s): those rows will be quarantined. TODO confirm"
    return [], "TODO: no column identifies rows; ask which columns do"


def draft_links(tables: dict, keys: dict) -> dict[str, list[dict]]:
    """Guess foreign keys: columns whose values mostly exist in another table's key."""
    rel = candidate_relationships(tables, min_containment=LINK_MIN_SHARE)
    single_keys = {(t, k[0]) for t, k in keys.items() if len(k) == 1}
    rel = rel[
        [(t, c) in single_keys for t, c in zip(rel["ref_table"], rel["ref_column"], strict=True)]
    ]
    links: dict[str, list[dict]] = {name: [] for name in tables}
    for (table, column), options in rel.groupby(["table", "column"], sort=True):
        options = options.assign(ref_rows=options["ref_table"].map(lambda t: len(tables[t])))
        options = options.sort_values(
            ["containment_pct", "ref_rows", "ref_table"], ascending=[False, False, True]
        )
        best = options.iloc[0]
        note = f"{best['containment_pct']}% of values found"
        if len(options) > 1:
            note += "; also matches " + ", ".join(options["ref_table"].iloc[1:])
        links[table].append(
            {
                "column": column,
                "ref_table": best["ref_table"],
                "ref_column": best["ref_column"],
                "note": note,
            }
        )
    return links


# --- Writing the draft --------------------------------------------------------
def py_set(values) -> str:
    """A set literal with sorted values, so the draft is the same every time."""
    return "{" + ", ".join(repr(v) for v in sorted(map(str, values))) + "}"


def comment(note: str | None) -> str:
    return f"  # {note}" if note else ""


def draft_contract(tables: dict[str, pd.DataFrame], source: str) -> str:
    """Return the Python source of a draft contract for these tables."""
    keys, key_notes = {}, {}
    for name, df in tables.items():
        keys[name], key_notes[name] = draft_key(df)
    links = draft_links(tables, keys)

    out = [
        f'"""Draft contract for `{source}`, generated from the data alone.',
        "",
        "Everything here is a GUESS from patterns in the data. Review it with someone",
        "who knows the business, fix what is wrong, and add what only they can say:",
        "which rows count for a purpose (datasets + filters), when two records are the",
        "same thing (identity), units, and what each category value means.",
        "Then run: uv run quote-desk clean --source <data> --contract <this file>",
        '"""',
        "",
        "from quote_desk.foundation.contract import (  # noqa: F401",
        "    Contract, Dataset, Filter, ForeignKey, Identity, Outliers, Table, Units,",
        ")",
        "",
        "CONTRACT = Contract(",
        f"    source={source!r},",
        "    tables=[",
    ]
    for name, df in tables.items():
        out += [
            "        Table(",
            f"            {name!r},",
            f"            primary_key={keys[name]!r},{comment(key_notes[name])}",
            "            types={",
        ]
        small_categories = []
        link_columns = {link["column"] for link in links[name]}
        for col in df.columns:
            kind, note = draft_type(df[col])
            if col in link_columns and kind == "category":
                kind, note = "str", "reference to another table"
            out.append(f"                {col!r}: {kind!r},{comment(note)}")
            distinct = df[col].dropna().unique()
            if kind == "category" and len(distinct) <= ALLOWED_VALUES_MAX:
                small_categories.append((col, distinct))
        out.append("            },")
        if links[name]:
            out.append("            foreign_keys=[")
            for link in links[name]:
                out.append(
                    f"                ForeignKey({link['column']!r}, {link['ref_table']!r}, "
                    f"{link['ref_column']!r}),{comment(link['note'])}"
                )
            out.append("            ],")
        for col, distinct in small_categories:
            out.append(
                f"            # allowed_values={{{col!r}: {py_set(distinct)}}},"
                "  # TODO: confirm what each value means"
            )
        out.append("        ),")
    out += [
        "    ],",
        "    # TODO: add datasets: which rows count for a purpose, and how to compare values.",
        "    datasets=[],",
        ")",
        "",
    ]
    return "\n".join(out)


def load_contract_file(path) -> Contract:
    """Load a contract from a Python file that defines `CONTRACT`.

    The file is executed as Python, so only load contracts you wrote or reviewed.
    """
    path = Path(path)
    name = "contract_" + re.sub(r"\W", "_", path.stem)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"{path}: not a Python file")
    module = importlib.util.module_from_spec(spec)
    writes_cache, sys.dont_write_bytecode = sys.dont_write_bytecode, True  # no __pycache__
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = writes_cache
    contract = getattr(module, "CONTRACT", None)
    if not isinstance(contract, Contract):
        raise ValueError(f"{path}: must define CONTRACT = Contract(...)")
    contract.validate()
    return contract
