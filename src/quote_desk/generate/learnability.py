"""Generator eval: is the synthetic cost data realistically hard to predict?

Fits an out-of-the-box LightGBM on the clean won jobs and reports its error
(MAPE: mean absolute percentage error) next to a "formula oracle" that knows
the exact cost formula but not the hidden factors. If LightGBM lands far below
~10%, the data is too easy to be a convincing demo; real quoting models
usually see 10-20%.

Run with `uv run quote-desk check-generator`.
"""

import lightgbm as lgb
import numpy as np
import pandas as pd

from quote_desk import config
from quote_desk.generate import commodity, synth_erp
from quote_desk.generate import cost_model as cm

NUMERIC = ["kva", "primary_v", "phase", "k_factor", "gauge", "quantity"]
CATEGORICAL = [
    "product_family", "secondary_v", "winding", "enclosure", "efficiency",
    "size", "finish", "nema_rating", "customer_id", "segment",
]  # fmt: skip
METALS = commodity.METALS
TEST_START = pd.Timestamp("2025-11-01")  # year 3 of the history


def won_jobs(tables: dict[str, pd.DataFrame], prices: pd.DataFrame) -> pd.DataFrame:
    """Won jobs joined with their item config, customer, and metal prices at quote date."""
    jobs = tables["jobs"].query("status == 'won'")
    df = jobs.merge(tables["items"], on="part_number").merge(
        tables["customers"][["customer_id", "segment"]], on="customer_id"
    )
    metal = pd.DataFrame([commodity.prices_on(prices, d) for d in df["quote_date"]])
    df = pd.concat([df.reset_index(drop=True), metal], axis=1)
    df["quote_date"] = pd.to_datetime(df["quote_date"])
    return df


def features(df: pd.DataFrame) -> pd.DataFrame:
    """Model inputs: config, quantity, customer, and metal prices. Nothing hidden."""
    X = df[NUMERIC + METALS].astype(float)
    for col in CATEGORICAL:
        X[col] = df[col].astype(str).astype("category")
    return X


def mape(predicted, actual) -> float:
    """Mean absolute percentage error, in percent."""
    predicted, actual = np.asarray(predicted), np.asarray(actual)
    return float(np.mean(np.abs(predicted - actual) / actual) * 100)


def lightgbm_mape(X, y, train, test, seed: int) -> float:
    """Train LightGBM on log(cost) for the train rows, return MAPE on the test rows.

    Log, because costs range from ~$100 to ~$30,000 and errors are relative.
    """
    model = lgb.LGBMRegressor(
        n_estimators=600,
        learning_rate=0.03,
        num_leaves=31,
        min_child_samples=10,
        random_state=seed,
        verbose=-1,
    )
    model.fit(X[train], np.log(y[train]))
    return mape(np.exp(model.predict(X[test])), y[test])


def oracle_mape(df: pd.DataFrame, rows) -> float:
    """MAPE of the exact planned-cost formula: the error left by hidden factors alone."""
    sub = df[rows]
    planned = [
        cm.expected_unit_cost(
            synth_erp.item_config(r),
            int(r["quantity"]),
            {m: r[m] for m in METALS},
            synth_erp.years_since_start(r["quote_date"]),
        )["total"]
        for _, r in sub.iterrows()
    ]
    return mape(planned, sub["actual_unit_cost"])


def evaluate(tables: dict[str, pd.DataFrame], prices: pd.DataFrame, seed: int) -> dict:
    """LightGBM MAPE on a random split and on the year-3 time split, plus the oracle."""
    df = won_jobs(tables, prices)
    X, y = features(df), df["actual_unit_cost"].to_numpy()
    rng = np.random.default_rng(seed)
    random_train = rng.random(len(df)) < 0.75
    time_train = (df["quote_date"] < TEST_START).to_numpy()
    return {
        "won_jobs": len(df),
        "lightgbm_random_split": lightgbm_mape(X, y, random_train, ~random_train, seed),
        "lightgbm_time_split": lightgbm_mape(X, y, time_train, ~time_train, seed),
        "oracle_time_split": oracle_mape(df, ~time_train),
    }


def check(seed: int = config.SEED, n_jobs: int = 3000) -> dict:
    """Build the clean ERP and print the eval."""
    tables = synth_erp.build_erp(seed, n_jobs, messy=False)
    result = evaluate(tables, commodity.load_prices(seed), seed)
    print(f"won jobs: {result['won_jobs']}")
    print(f"LightGBM, random 75/25 split:      MAPE {result['lightgbm_random_split']:5.1f}%")
    print(f"LightGBM, train yrs 1-2 -> yr 3:   MAPE {result['lightgbm_time_split']:5.1f}%")
    print(f"Formula oracle, yr 3:              MAPE {result['oracle_time_split']:5.1f}%")
    print("Target: LightGBM 10-20% (realistic), oracle somewhat below it.")
    return result
