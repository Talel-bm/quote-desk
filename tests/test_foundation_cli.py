"""New data end to end: load any source, draft a contract, clean it."""

import sqlite3

import pandas as pd
import pytest

from quote_desk import config
from quote_desk.foundation import cli
from quote_desk.foundation.contracts.lakeshore_erp import CONTRACT as HAND_WRITTEN
from quote_desk.foundation.draft_contract import (
    draft_contract,
    draft_key,
    draft_type,
    load_contract_file,
)
from quote_desk.foundation.load import load_source
from quote_desk.generate import synth_erp

SAMPLE = config.ROOT / "data" / "samples" / "field_service"


def test_load_source_accepts_folder_csv_and_sqlite(tmp_path):
    assert set(load_source(SAMPLE)) == {"sites", "technicians", "work_orders"}
    assert set(load_source(SAMPLE / "sites.csv")) == {"sites"}
    db = tmp_path / "x.db"
    with sqlite3.connect(db) as conn:
        pd.DataFrame({"a": [1]}).to_sql("t", conn, index=False)
    assert set(load_source(db)) == {"t"}
    with pytest.raises(ValueError):
        load_source(tmp_path / "data.xlsx")


def test_draft_type_tolerates_a_few_bad_values():
    assert draft_type(pd.Series([str(i) for i in range(40)] + ["four"])) == (
        "int",
        "1 value(s) are not numbers and will become missing",
    )
    assert draft_type(pd.Series(["2026-01-0" + str(i) for i in range(1, 10)]))[0] == "date"
    assert draft_type(pd.Series(["a", "b"] * 10))[0] == "category"
    assert draft_type(pd.Series([None, None])) == ("str", "always empty")


def test_draft_key_prefers_exact_then_nearly_unique():
    assert draft_key(pd.DataFrame({"id": ["a", "b"], "x": [1, 1]}))[0] == ["id"]
    nearly = pd.DataFrame({"id": [f"W{i}" for i in range(30)] + ["W0"], "x": [1] * 31})
    key, note = draft_key(nearly)
    assert key == ["id"] and note.startswith("1 repeated")


def test_draft_for_sample_is_valid_python_contract(tmp_path):
    path = tmp_path / "draft.py"
    path.write_text(draft_contract(load_source(SAMPLE), "field_service"), encoding="utf-8")
    contract = load_contract_file(path)
    orders = contract.table("work_orders")
    assert orders.primary_key == ["wo_id"]
    assert {(fk.column, fk.ref_table) for fk in orders.foreign_keys} == {
        ("site_id", "sites"),
        ("tech_id", "technicians"),
    }
    assert orders.types["site_id"] == "str"  # a reference, not a category
    assert orders.types["labor"] == "float"  # despite the value "four"
    assert not (tmp_path / "__pycache__").exists()


def test_draft_recovers_the_hand_written_erp_keys_and_links(tmp_path):
    raw = synth_erp.build_erp(seed=2, n_jobs=300)
    path = tmp_path / "erp_draft.py"
    path.write_text(draft_contract(raw, "erp"), encoding="utf-8")
    drafted = load_contract_file(path)
    for table in HAND_WRITTEN.tables:
        guess = drafted.table(table.name)
        if table.name != "inventory":  # hand-written key adds `location`; one value here
            assert guess.primary_key == table.primary_key, table.name
        links = {(fk.column, fk.ref_table) for fk in table.foreign_keys}
        assert {(fk.column, fk.ref_table) for fk in guess.foreign_keys} == links, table.name


def test_load_contract_file_rejects_files_without_contract(tmp_path):
    path = tmp_path / "nothing.py"
    path.write_text("X = 1\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_contract_file(path)


def test_clean_new_source_without_contract_drafts_one(tmp_path, capsys):
    report = cli.clean_command(str(SAMPLE), None, str(tmp_path), demo=False)
    assert (tmp_path / "contract_draft.py").exists()
    assert (tmp_path / "foundation.sqlite").exists()
    assert "No --contract given" in capsys.readouterr().out
    # Even the guessed contract catches the unknown technician (T9) for review.
    assert "| work_orders | W012 | orphan reference |" in report.read_text(encoding="utf-8")


def test_clean_new_source_with_reviewed_contract(tmp_path):
    contract = config.ROOT / "src" / "quote_desk" / "foundation" / "contracts"
    report = cli.clean_command(
        str(SAMPLE), str(contract / "field_service_demo.py"), str(tmp_path), demo=False
    )
    text = report.read_text(encoding="utf-8")
    assert "`completed_work`:** 20 of 23 rows kept" in text


def test_profile_command_writes_profile(tmp_path):
    path = cli.profile_command(str(SAMPLE), str(tmp_path))
    text = path.read_text(encoding="utf-8")
    assert "# Data profile: `field_service`" in text and "## `work_orders` columns" in text
