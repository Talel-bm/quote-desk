import pandas as pd
import pytest

from quote_desk.generate.fetch_commodities import parse_pink_sheet, select_window


def fake_sheet() -> pd.DataFrame:
    """A tiny copy of the Pink Sheet layout: title rows, names, units, months."""
    rows = [
        ["World Bank Commodity Price Data", None, None, None],
        ["Updated on ...", None, None, None],
        [None, "Aluminum", "Iron ore, cfr spot", "Copper"],
        [None, "($/mt)", "($/dmtu)", "($/mt)"],
        ["2023M10", 2100, 120.0, 8000],
        ["2023M11", 2200, 131.1, 8190],
        ["2023M12", 2182, 137.1, 8400],
    ]
    return pd.DataFrame(rows)


def test_parse_pink_sheet_reads_months_and_metals():
    prices = parse_pink_sheet(fake_sheet())
    assert list(prices["month"]) == ["2023-10", "2023-11", "2023-12"]
    assert prices.loc[1, "copper_usd_per_mt"] == 8190
    assert prices.loc[1, "aluminum_usd_per_mt"] == 2200
    assert prices.loc[1, "iron_ore_usd_per_dmtu"] == 131.1


def test_select_window_is_inclusive():
    window = select_window(parse_pink_sheet(fake_sheet()), "2023-11", "2023-12")
    assert list(window["month"]) == ["2023-11", "2023-12"]


def test_select_window_rejects_missing_values():
    sheet = fake_sheet()
    sheet.loc[5, 3] = None  # blank copper price in 2023-11
    with pytest.raises(ValueError):
        select_window(parse_pink_sheet(sheet), "2023-11", "2023-12")
