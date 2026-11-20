import sqlite3

import pandas as pd
import pytest

from quote_desk.foundation.contracts.lakeshore_erp import CONTRACT
from quote_desk.foundation.quality_report import build_foundation, md_table
from quote_desk.generate import synth_erp


@pytest.fixture(scope="module")
def raw():
    return synth_erp.build_erp(seed=5, n_jobs=400)


def test_md_table():
    df = pd.DataFrame({"a": [1, None], "b": ["x", "y"]})
    assert md_table(df).splitlines() == ["| a | b |", "|---|---|", "| 1.0 | x |", "|  | y |"]
    assert md_table(pd.DataFrame()) == "_none_"


def test_build_foundation_writes_db_and_report(raw, tmp_path):
    result = build_foundation(raw, CONTRACT, tmp_path / "f.sqlite", tmp_path / "r.md")
    with sqlite3.connect(tmp_path / "f.sqlite") as conn:
        names = {r[0] for r in conn.execute("select name from sqlite_master")}
    assert {"cost_history", "audit", "quarantine", "crosswalk", "review_queue", "jobs"} <= names

    report = (tmp_path / "r.md").read_text(encoding="utf-8")
    for heading in ["## Summary", "## Safeguards", "## Technical detail", "### Review queue"]:
        assert heading in report
    assert f"{len(result.datasets['cost_history']):,} of" in report


def test_report_is_identical_on_rerun(raw, tmp_path):
    build_foundation(raw, CONTRACT, tmp_path / "a.sqlite", tmp_path / "a.md")
    build_foundation(raw, CONTRACT, tmp_path / "b.sqlite", tmp_path / "b.md")
    assert (tmp_path / "a.md").read_text(encoding="utf-8") == (tmp_path / "b.md").read_text(
        encoding="utf-8"
    )
