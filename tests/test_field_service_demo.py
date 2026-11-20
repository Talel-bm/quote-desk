"""The same engine on an unrelated business: proof that Foundation is generic."""

import pytest

from quote_desk import config
from quote_desk.foundation.clean import run
from quote_desk.foundation.contracts.field_service_demo import CONTRACT
from quote_desk.foundation.load import load_csv_folder

SAMPLE = config.ROOT / "data" / "samples" / "field_service"


@pytest.fixture(scope="module")
def result():
    return run(load_csv_folder(SAMPLE), CONTRACT)


def test_duplicate_site_is_merged_by_address(result):
    merged = result.crosswalk.query("key != master_key")
    assert list(zip(merged["key"], merged["master_key"], strict=True)) == [("S04", "S01")]
    assert "S04" not in set(result.tables["work_orders"]["site_id"])


def test_minutes_become_hours(result):
    labor = result.tables["work_orders"].set_index("wo_id")["labor"]
    assert labor["W004"] == pytest.approx(1.5)  # 90 min
    assert labor["W008"] == pytest.approx(8.0)  # 480 min


def test_bad_rows_are_quarantined_or_logged(result):
    q = result.quarantine
    assert "repeated primary key" in set(q.query("table == 'work_orders'")["reason"])
    failed = result.audit.query("action == 'type_failed'")
    assert list(failed["key"]) == ["W022"]  # labor = "four"


def test_review_queue_holds_orphan_and_typo(result):
    review = dict(zip(result.review_queue["key"], result.review_queue["reason"], strict=True))
    assert review == {"W012": "orphan reference", "W009": "extreme value"}


def test_completed_work_keeps_only_done_orders(result):
    done = result.datasets["completed_work"]
    assert set(done["status"]) == {"done"}
    assert len(done) == 20
