import pandas as pd
import pytest

from quote_desk.generate.commodity import load_prices, price_on, prices_on, to_erp_table


def test_load_prices_covers_36_months_in_usd_per_kg():
    prices = load_prices(seed=1)
    assert len(prices) == 36
    assert prices["month"].iloc[0] == "2023-11"
    assert prices["month"].iloc[-1] == "2026-10"
    # Real World Bank values, converted from $/t to $/kg.
    assert prices["copper"].iloc[0] == pytest.approx(8.190)
    assert prices["aluminum"].iloc[-1] == pytest.approx(3.061)
    assert (prices[["copper", "aluminum", "electrical_steel"]] > 0).all().all()


def test_electrical_steel_is_reproducible_by_seed():
    a = load_prices(seed=1)["electrical_steel"]
    b = load_prices(seed=1)["electrical_steel"]
    c = load_prices(seed=2)["electrical_steel"]
    pd.testing.assert_series_equal(a, b)
    assert not a.equals(c)


def test_price_on_uses_the_month_of_the_date():
    prices = load_prices(seed=1)
    assert price_on(prices, "2023-11-17", "copper") == pytest.approx(8.190)
    assert price_on(prices, "2026-10-01", "copper") == pytest.approx(14.508)


def test_price_on_after_last_month_uses_latest_price():
    prices = load_prices(seed=1)
    assert prices_on(prices, "2026-12-15") == prices_on(prices, "2026-10-31")


def test_price_on_before_first_month_raises():
    with pytest.raises(ValueError):
        price_on(load_prices(seed=1), "2020-01-01", "copper")


def test_erp_table_labels_sources():
    table = to_erp_table(load_prices(seed=1))
    assert len(table) == 36 * 3
    sources = table.groupby("metal")["source"].first().to_dict()
    assert sources == {
        "aluminum": "worldbank",
        "copper": "worldbank",
        "electrical_steel": "synthetic",
    }
