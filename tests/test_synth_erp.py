import sqlite3

import pandas as pd
import pytest

from quote_desk.generate import synth_erp

TABLES = {
    "customers", "items", "boms", "routings", "jobs",
    "commodity_prices", "open_quotes", "inventory", "open_pos",
}  # fmt: skip


@pytest.fixture(scope="module")
def erp():
    """A small clean ERP (300 jobs) shared by the tests in this file."""
    return synth_erp.build_erp(seed=7, n_jobs=300, messy=False)


@pytest.fixture(scope="module")
def messy():
    """The same ERP with the deliberate mess applied."""
    return synth_erp.build_erp(seed=7, n_jobs=300)


def test_all_tables_are_built(erp):
    assert set(erp) == TABLES
    assert all(len(t) > 0 for t in erp.values())


def test_same_seed_gives_identical_tables(erp):
    again = synth_erp.build_erp(seed=7, n_jobs=300, messy=False)
    for name in TABLES:
        pd.testing.assert_frame_equal(erp[name], again[name])


def test_different_seed_gives_different_jobs(erp):
    other = synth_erp.build_erp(seed=8, n_jobs=300, messy=False)
    assert not erp["jobs"].equals(other["jobs"])


def test_jobs_have_outcomes_and_costs_only_when_won(erp):
    jobs = erp["jobs"]
    assert set(jobs["status"]) == {"won", "lost"}
    won, lost = jobs[jobs["status"] == "won"], jobs[jobs["status"] == "lost"]
    assert won["actual_unit_cost"].notna().all()
    assert lost["actual_unit_cost"].isna().all()
    assert 0.2 < len(won) / len(jobs) < 0.8


def test_jobs_reference_known_customers_and_parts(erp):
    jobs = erp["jobs"]
    assert jobs["customer_id"].isin(erp["customers"]["customer_id"]).all()
    assert jobs["part_number"].isin(erp["items"]["part_number"]).all()


def test_job_dates_stay_in_history_window(erp):
    dates = pd.to_datetime(erp["jobs"]["quote_date"])
    assert dates.min() >= synth_erp.HISTORY_START
    assert dates.max() <= synth_erp.HISTORY_END


def test_every_finished_item_has_bom_and_routing(erp):
    finished = erp["items"].query("item_type == 'finished'")["part_number"]
    assert set(finished) == set(erp["boms"]["parent_part"])
    assert set(finished) == set(erp["routings"]["part_number"])


def test_customer_emails_use_their_domain(erp):
    customers = erp["customers"]
    domains = customers["contact_email"].str.split("@").str[1]
    assert (domains == customers["email_domain"]).all()


def test_write_erp_creates_sqlite_with_all_tables(erp, tmp_path):
    path = synth_erp.write_erp(erp, tmp_path / "erp.sqlite")
    with sqlite3.connect(path) as conn:
        names = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
        n_jobs = conn.execute("select count(*) from jobs").fetchone()[0]
    assert names == TABLES
    assert n_jobs == len(erp["jobs"])


# --- Deliberate mess ------------------------------------------------------------
def test_messy_build_is_reproducible(messy):
    again = synth_erp.build_erp(seed=7, n_jobs=300)
    for name in TABLES:
        pd.testing.assert_frame_equal(messy[name], again[name])


def test_duplicate_parts_share_a_config(messy):
    finished = messy["items"].query("item_type == 'finished'")
    legacy = finished[finished["part_number"].str.startswith("L")]
    assert len(legacy) > 0
    config_cols = ["product_family", *synth_erp.TRANSFORMER_FIELDS, *synth_erp.ENCLOSURE_FIELDS]
    dupes = finished[config_cols].astype(str).duplicated(keep=False)
    assert dupes.sum() == 2 * len(legacy)
    assert messy["jobs"]["part_number"].isin(legacy["part_number"]).any()


def test_quotes_and_cancelled_jobs_are_mixed_in(messy):
    status = messy["jobs"]["status"]
    assert set(status) == {"won", "lost", "quote", "cancelled"}
    quotes = messy["jobs"][status == "quote"]
    assert quotes["actual_unit_cost"].isna().all()
    assert quotes["job_id"].str.startswith("Q").all()


def test_cancelled_jobs_have_partial_costs(erp, messy):
    clean = erp["jobs"].set_index("job_id")
    cancelled = messy["jobs"].query("status == 'cancelled'").set_index("job_id")
    before = clean.loc[cancelled.index, "actual_material_cost"]
    assert (cancelled["actual_material_cost"] < before).all()


def test_some_unit_costs_are_off_by_ten(erp, messy):
    clean = erp["jobs"].set_index("job_id")["actual_unit_cost"]
    won = messy["jobs"].query("status == 'won'").set_index("job_id")["actual_unit_cost"]
    ratio = (won / clean.loc[won.index]).dropna()
    assert ((ratio > 9.9) | (ratio < 0.101)).any()


def test_bom_units_mix_kg_and_lb(erp, messy):
    assert set(messy["boms"]["uom"]) == {"kg", "lb", "ea"}
    lb = messy["boms"].query("uom == 'lb'").dropna(subset=["qty"])
    kg = erp["boms"].loc[lb.index, "qty"]
    assert (lb["qty"] / kg).round(1).eq(2.2).all()


def test_about_three_percent_values_missing(messy):
    for table, columns in synth_erp.MISSING_COLUMNS.items():
        for col in columns:
            rate = messy[table][col].isna().mean()
            if table == "jobs" and col == "actual_labor_cost":
                continue  # already empty for lost jobs
            assert 0.0 < rate < 0.12, f"{table}.{col}: {rate:.1%}"
