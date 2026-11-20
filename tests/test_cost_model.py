import numpy as np
import pytest

from quote_desk.generate import cost_model as cm

PRICES = {"copper": 9.5, "aluminum": 2.6, "electrical_steel": 2.6}


def transformer(**overrides) -> dict:
    cfg = {
        "product_family": "transformer",
        "kva": 75,
        "primary_v": 480,
        "secondary_v": "208/120",
        "phase": 3,
        "winding": "copper",
        "k_factor": 1,
        "enclosure": "NEMA 1",
        "efficiency": "DOE 2016",
    }
    return cfg | overrides


def enclosure(**overrides) -> dict:
    cfg = {
        "product_family": "enclosure",
        "size": "24x20x8",
        "gauge": 14,
        "finish": "powder gray",
        "nema_rating": "NEMA 1",
    }
    return cfg | overrides


def total(cfg, qty=1, prices=PRICES):
    return cm.expected_unit_cost(cfg, qty, prices)["total"]


def test_75kva_transformer_cost_is_plausible():
    assert 1500 < total(transformer()) < 5000


def test_bigger_transformer_costs_more():
    assert total(transformer(kva=500)) > total(transformer(kva=75)) > total(transformer(kva=15))


def test_aluminum_winding_is_cheaper_and_lighter():
    cu, al = transformer(), transformer(winding="aluminum")
    assert cm.materials(al)["conductor_kg"] == pytest.approx(cm.materials(cu)["conductor_kg"] / 2)
    assert total(al) < total(cu)


def test_copper_price_raises_copper_unit_cost_only():
    expensive = PRICES | {"copper": 14.5}
    assert total(transformer(), prices=expensive) > total(transformer())
    assert total(transformer(winding="aluminum"), prices=expensive) == pytest.approx(
        total(transformer(winding="aluminum"))
    )


def test_options_add_cost():
    base = total(transformer())
    assert total(transformer(k_factor=13)) > base
    assert total(transformer(efficiency="premium")) > base
    assert total(transformer(enclosure="NEMA 3R")) > base


def test_learning_curve_lowers_labor_per_unit():
    assert cm.labor_hours(transformer(), 50) < cm.labor_hours(transformer(), 1)
    assert total(transformer(), qty=50) < total(transformer(), qty=1)


def test_enclosure_cost_grows_with_size_and_gauge():
    assert total(enclosure(size="48x36x12")) > total(enclosure())
    assert total(enclosure(gauge=12)) > total(enclosure(gauge=16))
    assert 50 < total(enclosure()) < 1000


def test_actual_cost_is_close_to_expected_on_average():
    rng = np.random.default_rng(0)
    actual = [cm.actual_unit_cost(transformer(), 1, PRICES, rng)["total"] for _ in range(2000)]
    assert np.mean(actual) == pytest.approx(total(transformer()), rel=0.03)
