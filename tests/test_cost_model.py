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
    actual = [cm.actual_unit_cost(transformer(), 1, PRICES, rng)["total"] for _ in range(4000)]
    # Rework and rare overruns push the average a little above the plan.
    assert np.mean(actual) == pytest.approx(total(transformer()), rel=0.05)
    assert np.mean(actual) > total(transformer())


def sample_totals(cfg, n=2000, seed=0, **conditions):
    rng = np.random.default_rng(seed)
    return np.array(
        [cm.actual_unit_cost(cfg, 1, PRICES, rng, **conditions)["total"] for _ in range(n)]
    )


def test_wage_inflation_raises_labor_over_time():
    later = cm.expected_unit_cost(transformer(), 1, PRICES, years=2.0)
    now = cm.expected_unit_cost(transformer(), 1, PRICES, years=0.0)
    assert later["labor"] == pytest.approx(now["labor"] * 1.04**2)
    assert later["material"] == now["material"]


def test_busy_shop_and_demanding_customer_cost_more():
    base = sample_totals(transformer()).mean()
    assert sample_totals(transformer(), shop_load=1.2).mean() > base
    assert sample_totals(transformer(), customer_factor=1.2).mean() > base
    # A quiet shop does not make jobs cheaper (no negative overtime).
    assert sample_totals(transformer(), shop_load=0.8).mean() == pytest.approx(base)


def test_unusual_options_make_cost_less_predictable():
    usual = transformer()
    rare = transformer(k_factor=13, primary_v=4160, efficiency="premium")
    assert cm.unusual_options(usual) == 0
    assert cm.unusual_options(rare) == 3

    def spread(cfg):
        totals = sample_totals(cfg)
        return np.std(np.log(totals))

    assert spread(rare) > spread(usual)


def test_actual_cost_flags_rework_and_overruns_at_expected_rates():
    rng = np.random.default_rng(1)
    runs = [cm.actual_unit_cost(transformer(), 1, PRICES, rng) for _ in range(5000)]
    assert np.mean([r["rework"] for r in runs]) == pytest.approx(cm.REWORK_RATE, abs=0.01)
    assert np.mean([r["overrun"] for r in runs]) == pytest.approx(cm.OVERRUN_RATE, abs=0.01)
