"""The cleaning engine on tiny hand-made tables (a made-up bike shop)."""

import json

import numpy as np
import pandas as pd
import pytest

from quote_desk.foundation import contract as c
from quote_desk.foundation.clean import run


def bike_shop():
    products = pd.DataFrame(
        {
            "sku": ["BK-1", "BK-2", "OLD-7", "BK-3", "PART-A"],
            "frame": ["steel", "carbon", "steel", "alu", None],
            "size": ["M", "L", "M", "S", None],  # OLD-7 is the same bike as BK-1
            "weight": ["12.5", "8", "12.5", "oops", "0.3"],
        }
    )
    rng = np.random.default_rng(0)
    prices = list(np.round(500 * rng.lognormal(0, 0.05, 11), 2)) + [5000.0]  # last = 10x typo
    sales = pd.DataFrame(
        {
            "sale_id": [f"S{i}" for i in range(12)] + ["S0", None],
            "sku": ["BK-1"] * 6 + ["OLD-7"] * 6 + ["BK-2", "BK-2"],
            "status": ["paid"] * 10 + ["refunded", "paid", "paid", "paid"],
            "price": prices + [900.0, 900.0],
            "when": ["2026-01-0" + str(i % 9 + 1) for i in range(14)],
        }
    )
    parts = pd.DataFrame(
        {
            "sku": ["BK-1", "BK-1", "BK-9"],
            "line": [1, 2, 1],
            "mass": [2.0, 4.4092, 1.0],
            "unit": ["kg", "lb", " kg "],
        }  # fmt: skip
    )
    return {"products": products, "sales": sales, "parts": parts}


CONTRACT = c.Contract(
    "bike_shop",
    tables=[
        c.Table(
            "products",
            ["sku"],
            {"sku": "str", "frame": "category", "size": "category", "weight": "float"},
            identity=c.Identity(["frame", "size"], usage_table="sales", usage_column="sku"),
        ),
        c.Table(
            "sales",
            ["sale_id"],
            {
                "sale_id": "str",
                "sku": "str",
                "status": "category",
                "price": "float",
                "when": "date",
            },
            foreign_keys=[c.ForeignKey("sku", "products", "sku")],
            allowed_values={"status": {"paid", "refunded"}},
        ),
        c.Table(
            "parts",
            ["sku", "line"],
            {"sku": "str", "line": "int", "mass": "float", "unit": "category"},
            foreign_keys=[c.ForeignKey("sku", "products", "sku")],
            units=c.Units("mass", "unit", {"kg": ("kg", 1.0), "lb": ("kg", 0.45359237)}),
        ),
    ],
    datasets=[
        c.Dataset(
            "sales_history",
            base_table="sales",
            joins=[("products", "sku")],
            filters=[c.Filter("status", {"paid"}, "refunds are not real sales")],
            outliers=c.Outliers("price", [["sku"]], min_group_size=5),
        )
    ],
)


@pytest.fixture(scope="module")
def result():
    return run(bike_shop(), CONTRACT)


def test_raw_tables_are_not_modified():
    raw = bike_shop()
    run(raw, CONTRACT)
    pd.testing.assert_frame_equal(raw["products"], bike_shop()["products"])


def test_bad_types_become_missing_and_are_logged(result):
    weights = result.tables["products"].set_index("sku")["weight"]
    assert pd.isna(weights["BK-3"])
    failed = result.audit.query("action == 'type_failed'")
    assert list(failed["key"]) == ["BK-3"] and failed["old_value"].iloc[0] == "oops"


def test_text_is_trimmed_and_units_converted(result):
    parts = result.tables["parts"].set_index(["sku", "line"])
    assert parts.loc[("BK-1", 2), "mass"] == pytest.approx(2.0, abs=1e-3)  # 4.4092 lb
    assert set(parts["unit"]) == {"kg"}  # " kg " was trimmed
    assert (result.audit["action"] == "unit_converted").sum() == 1


def test_empty_and_repeated_keys_are_quarantined(result):
    q = result.quarantine.query("table == 'sales'")
    assert set(q["reason"]) == {"empty primary key", "repeated primary key"}
    assert result.stats["tables"]["sales"] == {
        "rows_in": 14, "merged": 0, "quarantined": 2, "rows_out": 12,
    }  # fmt: skip
    original = json.loads(q[q["reason"] == "repeated primary key"]["row_json"].iloc[0])
    assert original["sku"] == "BK-2"  # the full raw row is kept


def test_duplicates_merge_into_most_used_key(result):
    cw = result.crosswalk.set_index("key")
    assert cw.loc["OLD-7", "master_key"] == "BK-1"  # tie on usage -> alphabetical
    assert "OLD-7" not in set(result.tables["products"]["sku"])
    assert "PART-A" not in cw.index  # no identity values -> never merged
    # OLD-7 sales now point at BK-1 (the BK-2 sales were the bad-key rows, quarantined).
    assert set(result.tables["sales"]["sku"]) == {"BK-1"}
    assert (result.audit["action"] == "remapped_to_master").sum() == 6


def test_orphans_go_to_review(result):
    orphan = result.review_queue.query("reason == 'orphan reference'")
    assert list(orphan["key"]) == ["BK-9|1"]
    link = next(r for r in result.stats["relationships"] if r["link"].startswith("parts.sku"))
    assert link["orphans"] == 1


def test_dataset_filters_with_reasons_and_flags_extremes(result):
    hist = result.datasets["sales_history"]
    assert "refunded" not in set(hist["status"])
    excluded = result.quarantine.query("table == 'sales_history'")
    assert excluded["reason"].iloc[0].startswith("status=refunded")
    flagged = hist[hist["is_outlier"]]
    assert list(flagged["sale_id"]) == ["S11"]  # the 10x price
    assert flagged["needs_review"].all()
    assert "S11" in set(result.review_queue["key"])


def test_outliers_fall_back_to_broader_groups_or_skip():
    from quote_desk.foundation.clean import Log, flag_outliers

    df = pd.DataFrame(
        {
            "id": list("abcdefgh"),
            "model": ["X"] * 6 + ["Y", "Y"],  # Y has only 2 rows
            "kind": ["bike"] * 6 + ["bike", "trike"],
            "price": [100, 102, 98, 101, 99, 103, 100, 100],
        }
    )
    rule = c.Outliers("price", [["model"], ["kind"]], min_group_size=5)
    out = flag_outliers(df, rule, "t", df["id"], Log())
    groups = dict(zip(out["id"], out["outlier_group"], strict=True))
    assert groups["a"] == "model"
    assert groups["g"] == "kind"  # Y too small -> compared with all bikes
    assert pd.isna(groups["h"])  # only trike: no usable group, not compared
    assert not out["is_outlier"].any()


def test_same_input_gives_identical_output():
    a, b = run(bike_shop(), CONTRACT), run(bike_shop(), CONTRACT)
    for name in a.tables:
        pd.testing.assert_frame_equal(a.tables[name], b.tables[name])
    pd.testing.assert_frame_equal(a.audit, b.audit)
    pd.testing.assert_frame_equal(a.datasets["sales_history"], b.datasets["sales_history"])
