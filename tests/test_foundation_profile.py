import sqlite3

import pandas as pd
import pytest

from quote_desk.foundation import contract as c
from quote_desk.foundation.load import load_sqlite
from quote_desk.foundation.profile import (
    candidate_keys,
    candidate_relationships,
    guess_type,
    profile,
    shape,
)

# A tiny made-up source: a library with books and loans. Nothing ERP-specific.
BOOKS = pd.DataFrame(
    {"isbn": ["B-001", "B-002", "B-003"], "title": ["A", "B", "C"], "price": [9.5, 12.0, 9.5]}
)
LOANS = pd.DataFrame(
    {
        "loan_id": [1, 2, 3, 4],
        "isbn": ["B-001", "B-001", "B-003", "X-999"],  # X-999 is an orphan
        "date": ["2026-01-02", "2026-01-05", None, "2026-02-01"],
    }
)


def test_shape_reveals_numbering_schemes():
    assert shape("TX-75-3P-480") == "A-9-9A-9"
    assert shape("L40001") == "A9"


def test_guess_type():
    assert guess_type(pd.Series(["1", "2", None])) == "int"
    assert guess_type(pd.Series([1.5, 2.0])) == "float"
    assert guess_type(pd.Series(["2026-01-02", None])) == "date"
    assert guess_type(pd.Series(["abc", "1"])) == "text"
    assert guess_type(pd.Series([None, None])) == "empty"


def test_candidate_keys_ignore_floats_and_find_pairs():
    assert candidate_keys(BOOKS) == [["isbn"], ["title"]]
    lines = pd.DataFrame({"order": ["A", "A", "B"], "line": [1, 2, 1], "qty": [1.5, 2.5, 3.5]})
    assert candidate_keys(lines) == [["order", "line"]]


def test_relationships_measure_how_many_links_resolve():
    rel = candidate_relationships({"books": BOOKS, "loans": LOANS})
    link = rel[(rel["table"] == "loans") & (rel["column"] == "isbn")].iloc[0]
    assert link["ref_table"] == "books"
    assert link["containment_pct"] == pytest.approx(66.7)  # 2 of 3 distinct isbns resolve


def test_profile_reports_missing_values():
    report = profile({"books": BOOKS, "loans": LOANS})
    cols = report["columns"]["loans"].set_index("column")
    assert cols.loc["date", "missing_pct"] == 25.0
    assert set(report["summary"]["table"]) == {"books", "loans"}


def test_load_sqlite_is_read_only(tmp_path):
    path = tmp_path / "src.sqlite"
    with sqlite3.connect(path) as conn:
        BOOKS.to_sql("books", conn, index=False)
    tables = load_sqlite(path)
    pd.testing.assert_frame_equal(tables["books"], BOOKS)
    with pytest.raises(FileNotFoundError):
        load_sqlite(tmp_path / "missing.sqlite")


def test_contract_validate_catches_mistakes():
    good = c.Contract(
        "library",
        [
            c.Table("books", ["isbn"], {"price": "float"}),
            c.Table("loans", ["loan_id"], {}, [c.ForeignKey("isbn", "books", "isbn")]),
        ],
    )
    good.validate()
    bad_type = c.Contract("x", [c.Table("books", ["isbn"], {"price": "money"})])
    with pytest.raises(ValueError):
        bad_type.validate()
    bad_ref = c.Contract(
        "x", [c.Table("loans", ["id"], {}, [c.ForeignKey("isbn", "nowhere", "isbn")])]
    )
    with pytest.raises(ValueError):
        bad_ref.validate()
