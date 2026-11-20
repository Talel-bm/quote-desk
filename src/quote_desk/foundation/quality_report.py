"""Run Foundation end to end and write the data quality report.

The report has two parts: a plain-language summary for business readers, then
the technical detail (reconciliation, relationships, changes, review queue,
and profile findings no rule handled) for engineers.
"""

import sqlite3
from pathlib import Path

import pandas as pd

from quote_desk.foundation.clean import Result, run
from quote_desk.foundation.contract import Contract
from quote_desk.foundation.profile import profile


# --- Saving -------------------------------------------------------------------
def write_foundation(result: Result, path: Path) -> Path:
    """Write cleaned tables, datasets and logs to a fresh SQLite file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    outputs = {
        **result.tables,
        **result.datasets,
        "crosswalk": result.crosswalk,
        "audit": result.audit,
        "quarantine": result.quarantine,
        "review_queue": result.review_queue,
    }
    with sqlite3.connect(path) as conn:
        for name, df in outputs.items():
            df.to_sql(name, conn, index=False)
    return path


# --- Markdown helpers ---------------------------------------------------------
def md_table(df: pd.DataFrame) -> str:
    """Render a DataFrame as a Markdown table (no extra dependency needed)."""
    if df.empty:
        return "_none_"
    cells = df.astype(object).where(df.notna(), "")
    lines = ["| " + " | ".join(map(str, df.columns)) + " |", "|" + "---|" * df.shape[1]]
    lines += [
        "| " + " | ".join(str(v) for v in row) + " |" for row in cells.itertuples(index=False)
    ]
    return "\n".join(lines)


def n(x: int) -> str:
    """Thousands separator: 3065 -> '3,065'."""
    return f"{x:,}"


def count(x: int, singular: str, plural: str | None = None) -> str:
    """'1 record', '20 records', '1,270 quantities'."""
    return f"{n(x)} {singular if x == 1 else plural or singular + 's'}"


# --- Report sections ----------------------------------------------------------
def missing_values(raw_profile: dict) -> pd.DataFrame:
    """Columns that have missing values in the raw data (left for the model layer)."""
    rows = [
        {"table": t, "column": r["column"], "missing_pct": r["missing_pct"]}
        for t, cols in raw_profile["columns"].items()
        for _, r in cols.iterrows()
        if r["missing_pct"] > 0
    ]
    return pd.DataFrame(rows, columns=["table", "column", "missing_pct"])


def summary_section(contract: Contract, raw: dict, result: Result) -> list[str]:
    """Plain-language summary: what we read, what we fixed, what needs a person."""
    rel = pd.DataFrame(result.stats["relationships"])
    filled = int(rel["rows"].sum() - rel["empty"].sum()) if not rel.empty else 0
    resolved = int(rel["resolved"].sum()) if not rel.empty else 0
    pct = f"{resolved / filled:.1%}" if filled else "n/a"
    actions = result.audit["action"].value_counts()
    merged = int((result.crosswalk["key"] != result.crosswalk["master_key"]).sum())

    lines = [
        "## Summary",
        "",
        f"- **Read** {len(raw)} tables and {n(sum(len(df) for df in raw.values()))} rows from "
        f"`{contract.source}`, read-only. The source was not changed.",
        f"- **Entities and relationships:** {len(contract.tables)} entity types and "
        f"{len(rel)} relationships. {n(resolved)} of {n(filled)} links ({pct}) point to a "
        "known record.",
    ]
    for name, counts in result.stats["datasets"].items():
        excluded = result.quarantine[result.quarantine["table"] == name]
        reasons = excluded["reason"].str.split(":").str[0].value_counts()
        detail = ", ".join(f"{n(c)} with {r}" for r, c in reasons.items())
        lines.append(
            f"- **`{name}`:** {n(counts['rows_kept'])} of {n(counts['rows_in'])} rows kept. "
            f"Excluded with a reason: {detail or 'none'}."
        )
    remapped = int(actions.get("remapped_to_master", 0))
    converted = int(actions.get("unit_converted", 0))
    flagged = int(actions.get("flagged_outlier", 0))
    lines += [
        f"- **Fixed automatically and logged:** {count(merged, 'record')} stored under a second "
        f"key merged into its master ({count(remapped, 'reference')} repointed); "
        f"{count(converted, 'quantity', 'quantities')} converted to a standard unit.",
        f"- **Flagged, not removed:** {count(flagged, 'value')} unusual compared with similar "
        f"records. {count(len(result.review_queue), 'case')} extreme or unresolvable, waiting "
        "in the **review queue** for a person.",
        f"- **Left for the model layer:** missing values in "
        f"{len(missing_values(profile(raw)))} columns are kept as missing, not guessed.",
        "- **Nothing was deleted:** every row is kept, merged into its master (see crosswalk), "
        "or quarantined with its reason.",
        "",
    ]
    return lines


def safeguards_section() -> list[str]:
    """How each safeguard is implemented in this run."""
    rows = pd.DataFrame(
        [
            (
                "Agreed sources",
                "A written contract per source: keys, links, types, units, "
                "which rows count. Every rule is visible in one file.",
            ),  # fmt: skip
            ("Controlled access", "The source is opened read-only; outputs go to a separate file."),
            (
                "Tested calculations",
                "The engine is unit-tested on small hand-made tables, and "
                "its detection is scored against known-clean data.",
            ),  # fmt: skip
            (
                "Human review",
                "Extreme or unresolvable cases go to a review queue; everything "
                "else is fixed automatically and logged.",
            ),  # fmt: skip
            (
                "Record of actions",
                "Every changed value, merge, flag and exclusion is in the "
                "`audit` and `quarantine` tables with its rule and original value.",
            ),  # fmt: skip
        ],
        columns=["Safeguard", "In this run"],
    )
    return ["## Safeguards", "", md_table(rows), ""]


def technical_section(raw: dict, raw_profile: dict, result: Result) -> list[str]:
    """Engineer-facing detail."""
    recon = pd.DataFrame(
        [{"table": t, **s} for t, s in result.stats["tables"].items()],
        columns=["table", "rows_in", "merged", "quarantined", "rows_out"],
    )
    rel = pd.DataFrame(result.stats["relationships"])
    if not rel.empty:
        filled = rel["rows"] - rel["empty"]
        rel["resolved_pct"] = (rel["resolved"] / filled.where(filled > 0) * 100).round(1)
    excluded = (
        result.quarantine.groupby(["table", "reason"]).size().reset_index(name="rows")
        if not result.quarantine.empty
        else pd.DataFrame()
    )
    changes = result.audit.groupby(["table", "action", "rule"]).size().reset_index(name="count")
    merged = result.crosswalk[result.crosswalk["key"] != result.crosswalk["master_key"]]

    lines = [
        "## Technical detail",
        "",
        "### Reconciliation (rows in = merged + quarantined + rows out)",
        "",
        md_table(recon),
        "",
        "### Relationships",
        "",
        md_table(rel),
        "",
        "### Excluded and quarantined rows",
        "",
        md_table(excluded),
        "",
        "### Changes and flags (audit log summary)",
        "",
        md_table(changes),
        "",
    ]
    for name, df in result.datasets.items():
        if "outlier_group" in df:
            levels = df["outlier_group"].fillna("not compared (group too small)")
            lines += [
                f"### `{name}`: comparison group used for each row",
                "",
                md_table(levels.value_counts().rename_axis("group").reset_index(name="rows")),
                "",
            ]
    lines += [
        "### Review queue",
        "",
        md_table(result.review_queue),
        "",
        "### Merged duplicates (crosswalk, non-master keys)",
        "",
        md_table(merged),
        "",
        "### Findings no rule handled",
        "",
        f"Tables without a contract: {', '.join(result.stats['uncontracted']) or 'none'}.",
        "",
        "Missing values (raw data, left as missing):",
        "",
        md_table(missing_values(raw_profile)),
        "",
        "### Raw profile",
        "",
        md_table(raw_profile["summary"]),
        "",
        "Links discovered from the data alone (before the contract):",
        "",
        md_table(raw_profile["relationships"]),
        "",
    ]
    return lines


def render(contract: Contract, raw: dict, raw_profile: dict, result: Result) -> str:
    """The full report as Markdown."""
    lines = [
        f"# Data quality report: `{contract.source}`",
        "",
        "Generated by `uv run quote-desk clean`. The same input and contract always produce "
        "the same report.",
        "",
        *summary_section(contract, raw, result),
        *safeguards_section(),
        *technical_section(raw, raw_profile, result),
    ]
    return "\n".join(lines)


# --- Entry point --------------------------------------------------------------
def build_foundation(
    raw: dict[str, pd.DataFrame], contract: Contract, db_path: Path, report_path: Path
) -> Result:
    """Profile, clean, save and report. Returns the result for further use."""
    raw_profile = profile(raw)
    result = run(raw, contract)
    write_foundation(result, db_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render(contract, raw, raw_profile, result), encoding="utf-8")
    return result
