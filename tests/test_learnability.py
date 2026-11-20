import numpy as np
import pytest

from quote_desk.generate import commodity, learnability, synth_erp


@pytest.fixture(scope="module")
def small():
    tables = synth_erp.build_erp(seed=3, n_jobs=600, messy=False)
    return tables, commodity.load_prices(3)


def test_mape_is_a_percentage():
    assert learnability.mape([110, 90], [100, 100]) == pytest.approx(10.0)


def test_features_use_only_visible_columns(small):
    tables, prices = small
    X = learnability.features(learnability.won_jobs(tables, prices))
    assert "actual_unit_cost" not in X.columns
    assert not any(col.startswith("_") for col in X.columns)
    assert set(learnability.METALS) <= set(X.columns)


def test_evaluate_returns_sensible_errors(small):
    tables, prices = small
    result = learnability.evaluate(tables, prices, seed=3)
    assert result["won_jobs"] > 100
    for key in ["lightgbm_random_split", "lightgbm_time_split", "oracle_time_split"]:
        assert np.isfinite(result[key])
        assert 1 < result[key] < 60, f"{key}: {result[key]:.1f}%"
