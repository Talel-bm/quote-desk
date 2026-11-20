"""The generic cleaning engine: apply a contract to raw tables.

Principles:
- Raw tables are never changed; the engine works on copies.
- Nothing disappears silently. Every row ends up kept, merged into a
  duplicate's master, or quarantined with a reason.
- Every change is written to an audit log (table, key, column, old, new, rule),
  so any cleaned value can be traced back to the raw data.
- Suspicious values are flagged, not removed. Only extreme cases go to a
  human review queue.
- Missing values are left missing; the model layer decides what to do.
- Same input + same contract -> identical output.
"""

import json
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from quote_desk.foundation.contract import Contract, Dataset, Outliers, Table

MAD_TO_SD = 1.4826  # scales the median absolute deviation to match a standard deviation


@dataclass
class Log:
    """Collects everything the engine does, for the report and for lineage."""

    audit: list[dict] = field(default_factory=list)
    quarantine: list[dict] = field(default_factory=list)
    review: list[dict] = field(default_factory=list)

    def change(self, table, key, column, action, rule, old, new):
        """Record one changed (or flagged) value."""
        self.audit.append(
            {
                "table": table,
                "key": key,
                "column": column,
                "action": action,
                "rule": rule,
                "old_value": None if pd.isna(old) else str(old),
                "new_value": None if pd.isna(new) else str(new),
            }
        )

    def quarantine_rows(self, table, rows: pd.DataFrame, keys: pd.Series, reasons):
        """Move rows out of a table, keeping the full raw row and the reason."""
        reasons = reasons if isinstance(reasons, pd.Series) else pd.Series(reasons, rows.index)
        for idx, row in rows.iterrows():
            self.quarantine.append(
                {
                    "table": table,
                    "key": keys[idx],
                    "reason": reasons[idx],
                    "row_json": json.dumps(row.to_dict(), default=str, sort_keys=True),
                }
            )

    def needs_review(self, table, key, reason, detail):
        """Send one case to a person: the engine could not decide safely."""
        self.review.append({"table": table, "key": key, "reason": reason, "detail": detail})


@dataclass
class Result:
    """Everything one run produces."""

    tables: dict[str, pd.DataFrame]
    datasets: dict[str, pd.DataFrame]
    crosswalk: pd.DataFrame
    audit: pd.DataFrame
    quarantine: pd.DataFrame
    review_queue: pd.DataFrame
    stats: dict


# --- Helpers ------------------------------------------------------------------
def row_keys(df: pd.DataFrame, key_columns: list[str]) -> pd.Series:
    """A readable key per row, e.g. 'J100001' or 'TX-75-...|2' for two-column keys."""
    if not key_columns:
        return pd.Series(df.index.astype(str), index=df.index)
    return joined_text(df[key_columns])


def joined_text(df: pd.DataFrame) -> pd.Series:
    """Join several columns into one text value per row; missing becomes ''."""
    as_text = df.apply(lambda col: col.map(lambda v: "" if pd.isna(v) else str(v)))
    return as_text.agg("|".join, axis=1)


def normalize_text(series: pd.Series) -> pd.Series:
    """Trim and collapse whitespace; empty strings become missing."""
    out = series.astype("string").str.strip().str.replace(r"\s+", " ", regex=True)
    return out.mask(out == "").astype(object).where(out.notna(), None)


# --- Step 1: types ------------------------------------------------------------
def enforce_types(df: pd.DataFrame, spec: Table, keys: pd.Series, log: Log) -> pd.DataFrame:
    """Give each column its declared type. Values that cannot be converted
    become missing, and each one is logged."""
    df = df.copy()
    for col, kind in spec.types.items():
        if col not in df.columns:
            log.change(spec.name, None, col, "missing_column", "contract type", None, None)
            continue
        before = df[col]
        if kind in ("str", "category"):
            after = normalize_text(before)
        elif kind in ("int", "float"):
            after = pd.to_numeric(before, errors="coerce")
            if kind == "int":
                whole = after.isna() | (after == after.round())
                after = after.where(whole).round().astype("Int64")
        else:  # date, stored as 'YYYY-MM-DD' text
            parsed = pd.to_datetime(before, errors="coerce", format="mixed")
            after = parsed.dt.strftime("%Y-%m-%d").astype(object).where(parsed.notna(), None)
        failed = before.notna() & pd.isna(after) & (before.astype(str).str.strip() != "")
        for idx in df.index[failed]:
            log.change(spec.name, keys[idx], col, "type_failed", f"{kind}", before[idx], None)
        df[col] = after
    return df


# --- Step 2: allowed values ---------------------------------------------------
def check_allowed_values(df: pd.DataFrame, spec: Table, keys: pd.Series, log: Log) -> None:
    """Flag values the customer did not list as possible (kept as-is)."""
    for col, allowed in spec.allowed_values.items():
        unexpected = df[col].notna() & ~df[col].isin(allowed)
        for idx in df.index[unexpected]:
            log.change(
                spec.name,
                keys[idx],
                col,
                "unexpected_value",
                "allowed values",
                df[col][idx],
                df[col][idx],
            )


# --- Step 3: units ------------------------------------------------------------
def convert_units(df: pd.DataFrame, spec: Table, keys: pd.Series, log: Log) -> pd.DataFrame:
    """Convert every quantity to its canonical unit (e.g. lb -> kg)."""
    units = spec.units
    if units is None:
        return df
    df = df.copy()
    for idx, uom in df[units.uom_column].items():
        if pd.isna(uom):
            continue
        if uom not in units.conversions:
            log.change(spec.name, keys[idx], units.uom_column, "unknown_unit", "units", uom, uom)
            continue
        canonical, factor = units.conversions[uom]
        if uom == canonical:
            continue
        old_qty = df.at[idx, units.qty_column]
        new_qty = None if pd.isna(old_qty) else round(float(old_qty) * factor, 4)
        df.at[idx, units.qty_column] = new_qty
        df.at[idx, units.uom_column] = canonical
        log.change(
            spec.name,
            keys[idx],
            units.qty_column,
            "unit_converted",
            f"{uom}->{canonical}",
            f"{old_qty} {uom}",
            f"{new_qty} {canonical}",
        )
    return df


# --- Step 4: primary keys -----------------------------------------------------
def enforce_primary_key(df: pd.DataFrame, spec: Table, log: Log) -> pd.DataFrame:
    """Quarantine rows with an empty key, and repeats of a key (first one kept)."""
    keys = row_keys(df, spec.primary_key)
    empty = df[spec.primary_key].isna().any(axis=1)
    repeated = ~empty & keys.duplicated(keep="first")
    log.quarantine_rows(spec.name, df[empty], keys, "empty primary key")
    log.quarantine_rows(spec.name, df[repeated], keys, "repeated primary key")
    return df[~empty & ~repeated]


# --- Step 5: duplicate entities -----------------------------------------------
def merge_duplicates(tables: dict, spec: Table, log: Log) -> pd.DataFrame:
    """Find rows that describe the same thing under different keys.

    Rows match when every identity column is equal. The key used most often
    in the usage table becomes the master (ties: alphabetical). Non-masters
    leave the table; the crosswalk maps them to their master.
    """
    ident, (key_col,) = spec.identity, spec.primary_key
    df = tables[spec.name]
    signature = joined_text(df[ident.columns])
    has_identity = df[ident.columns].notna().any(axis=1)
    usage = tables[ident.usage_table][ident.usage_column].value_counts()

    rows = []
    for _, group in df[has_identity].groupby(signature[has_identity], sort=True):
        if len(group) < 2:
            continue
        ranked = group.assign(_uses=group[key_col].map(usage).fillna(0))
        ranked = ranked.sort_values(["_uses", key_col], ascending=[False, True])
        master = ranked[key_col].iloc[0]
        for key, uses in zip(ranked[key_col], ranked["_uses"], strict=True):
            rows.append(
                {
                    "table": spec.name,
                    "key": key,
                    "master_key": master,
                    "uses": int(uses),
                    "group_size": len(group),
                }
            )
            if key != master:
                log.change(
                    spec.name, key, key_col, "merged_duplicate", "identity columns", key, master
                )
    return pd.DataFrame(rows, columns=["table", "key", "master_key", "uses", "group_size"])


def remap_references(tables: dict, contract: Contract, crosswalk: pd.DataFrame, log: Log) -> None:
    """Point every foreign key at the master record instead of a merged duplicate."""
    for target in crosswalk["table"].unique():
        mapping = crosswalk[
            (crosswalk["table"] == target) & (crosswalk["key"] != crosswalk["master_key"])
        ]
        mapping = dict(zip(mapping["key"], mapping["master_key"], strict=True))
        for spec in contract.tables:
            keys = row_keys(tables[spec.name], spec.primary_key)
            for fk in spec.foreign_keys:
                if fk.ref_table != target:
                    continue
                col = tables[spec.name][fk.column]
                hit = col.isin(mapping.keys())
                for idx in col.index[hit]:
                    log.change(
                        spec.name,
                        keys[idx],
                        fk.column,
                        "remapped_to_master",
                        f"crosswalk {target}",
                        col[idx],
                        mapping[col[idx]],
                    )
                tables[spec.name][fk.column] = col.where(~hit, col.map(mapping))


# --- Step 6: relationships ----------------------------------------------------
def check_relationships(tables: dict, contract: Contract, log: Log) -> list[dict]:
    """For each foreign key: how many links resolve? Orphans go to review."""
    results = []
    for spec in contract.tables:
        df = tables[spec.name]
        keys = row_keys(df, spec.primary_key)
        for fk in spec.foreign_keys:
            known = set(tables[fk.ref_table][fk.ref_column].dropna())
            filled = df[fk.column].notna()
            orphan = filled & ~df[fk.column].isin(known)
            for idx in df.index[orphan]:
                log.needs_review(
                    spec.name,
                    keys[idx],
                    "orphan reference",
                    f"{fk.column}={df[fk.column][idx]} not in {fk.ref_table}",
                )
            results.append(
                {
                    "link": f"{spec.name}.{fk.column} -> {fk.ref_table}.{fk.ref_column}",
                    "rows": int(len(df)),
                    "empty": int((~filled).sum()),
                    "resolved": int((filled & ~orphan).sum()),
                    "orphans": int(orphan.sum()),
                }
            )
    return results


# --- Step 7: datasets ---------------------------------------------------------
def apply_filters(df: pd.DataFrame, dataset: Dataset, keys: pd.Series, log: Log) -> pd.DataFrame:
    """Keep the rows the dataset is for; quarantine the rest with a reason."""
    keep = pd.Series(True, index=df.index)
    for f in dataset.filters:
        excluded = keep & ~df[f.column].isin(f.keep)
        reasons = df[f.column][excluded].map(
            lambda v, f=f: f"{f.column}={v}: not used ({f.reason})"
        )
        log.quarantine_rows(dataset.name, df[excluded], keys, reasons)
        keep &= ~excluded
    return df[keep]


def join_tables(df: pd.DataFrame, dataset: Dataset, tables: dict) -> pd.DataFrame:
    """Left-join reference tables; columns the base already has are not duplicated."""
    for table, column in dataset.joins:
        ref = tables[table]
        extra = [c for c in ref.columns if c not in df.columns or c == column]
        df = df.merge(ref[extra], on=column, how="left", validate="many_to_one")
    return df


def flag_outliers(
    df: pd.DataFrame, rule: Outliers, dataset: str, keys: pd.Series, log: Log
) -> pd.DataFrame:
    """Flag values far from comparable rows, using robust statistics.

    On a log scale, each row is compared with the median of its group, and
    the distance is divided by the group's spread (median absolute deviation),
    so a few extreme values cannot hide themselves by inflating the average.
    """
    df = df.copy()
    log_value = np.log(pd.to_numeric(df[rule.column], errors="coerce").where(lambda v: v > 0))
    median = pd.Series(np.nan, index=df.index)
    spread = pd.Series(np.nan, index=df.index)
    level_used = pd.Series(None, index=df.index, dtype=object)

    for level in rule.group_levels:
        todo = median.isna() & log_value.notna() & df[level].notna().all(axis=1)
        if not todo.any():
            continue
        grouped = log_value.groupby([df[c] for c in level])
        size = grouped.transform("count")
        med = grouped.transform("median")
        mad = (log_value - med).abs().groupby([df[c] for c in level]).transform("median")
        usable = todo & (size >= rule.min_group_size) & (mad > 0)
        median[usable], spread[usable] = med[usable], mad[usable] * MAD_TO_SD
        level_used[usable] = "+".join(level)

    z = (log_value - median) / spread
    ratio = np.exp((log_value - median).abs())
    df["outlier_z"] = z.round(2)
    df["outlier_group"] = level_used
    df["is_outlier"] = (z.abs() > rule.z_threshold).fillna(False)
    df["needs_review"] = (df["is_outlier"] & (ratio >= rule.review_ratio)).fillna(False)

    for idx in df.index[df["is_outlier"]]:
        typical = float(np.exp(median[idx]))
        log.change(
            dataset,
            keys[idx],
            rule.column,
            "flagged_outlier",
            f"robust z > {rule.z_threshold}",
            df[rule.column][idx],
            f"typical {typical:.2f}, z={z[idx]:.1f}",
        )
        if df.at[idx, "needs_review"]:
            log.needs_review(
                dataset,
                keys[idx],
                "extreme value",
                f"{rule.column}={df[rule.column][idx]} is {ratio[idx]:.1f}x the typical "
                f"{typical:.2f} for its {level_used[idx]} group",
            )
    return df


def build_dataset(
    tables: dict, contract: Contract, dataset: Dataset, log: Log
) -> tuple[pd.DataFrame, dict]:
    """Filter, join and flag one dataset; return it with its row counts."""
    base = contract.table(dataset.base_table)
    df = tables[dataset.base_table]
    keys = row_keys(df, base.primary_key)
    kept = apply_filters(df, dataset, keys, log)
    joined = join_tables(kept.reset_index(drop=True), dataset, tables)
    joined_keys = row_keys(joined, base.primary_key)
    if dataset.outliers:
        joined = flag_outliers(joined, dataset.outliers, dataset.name, joined_keys, log)
    counts = {"rows_in": len(df), "rows_kept": len(joined), "rows_excluded": len(df) - len(kept)}
    return joined, counts


# --- The whole run ------------------------------------------------------------
def run(raw: dict[str, pd.DataFrame], contract: Contract) -> Result:
    """Apply a contract to raw tables and return cleaned data plus full logs."""
    contract.validate()
    log = Log()
    tables, stats = (
        {},
        {"tables": {}, "uncontracted": sorted(set(raw) - {t.name for t in contract.tables})},
    )

    for spec in contract.tables:
        df = raw[spec.name].copy()
        keys = row_keys(df, spec.primary_key)
        df = enforce_types(df, spec, keys, log)
        keys = row_keys(df, spec.primary_key)
        check_allowed_values(df, spec, keys, log)
        df = convert_units(df, spec, keys, log)
        df = enforce_primary_key(df, spec, log)
        tables[spec.name] = df
        stats["tables"][spec.name] = {"rows_in": len(raw[spec.name])}

    crosswalks = [merge_duplicates(tables, spec, log) for spec in contract.tables if spec.identity]
    crosswalk = (
        pd.concat(crosswalks, ignore_index=True)
        if crosswalks
        else pd.DataFrame(columns=["table", "key", "master_key", "uses", "group_size"])
    )
    for spec in contract.tables:
        if spec.identity:
            merged = crosswalk[
                (crosswalk["table"] == spec.name) & (crosswalk["key"] != crosswalk["master_key"])
            ]
            tables[spec.name] = tables[spec.name][
                ~tables[spec.name][spec.primary_key[0]].isin(merged["key"])
            ]
    remap_references(tables, contract, crosswalk, log)

    stats["relationships"] = check_relationships(tables, contract, log)

    datasets = {}
    stats["datasets"] = {}
    for dataset in contract.datasets:
        datasets[dataset.name], stats["datasets"][dataset.name] = build_dataset(
            tables, contract, dataset, log
        )

    quarantine = pd.DataFrame(log.quarantine, columns=["table", "key", "reason", "row_json"])
    for spec in contract.tables:
        tables[spec.name] = tables[spec.name].reset_index(drop=True)
        s = stats["tables"][spec.name]
        s["merged"] = int(
            (
                (crosswalk["table"] == spec.name) & (crosswalk["key"] != crosswalk["master_key"])
            ).sum()
        )
        s["quarantined"] = int((quarantine["table"] == spec.name).sum())
        s["rows_out"] = len(tables[spec.name])

    return Result(
        tables=tables,
        datasets=datasets,
        crosswalk=crosswalk,
        audit=pd.DataFrame(
            log.audit,
            columns=["table", "key", "column", "action", "rule", "old_value", "new_value"],
        ),
        quarantine=quarantine,
        review_queue=pd.DataFrame(log.review, columns=["table", "key", "reason", "detail"]),
        stats=stats,
    )
