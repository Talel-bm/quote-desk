"""Score Foundation against ground truth.

The generator can build the same ERP with and without its deliberate mess.
The engine only ever sees the messy version; these tests use the clean one
as the answer key, the way a model is scored on held-out labels.
"""

import pytest

from quote_desk.foundation.clean import run
from quote_desk.foundation.contracts.lakeshore_erp import CONFIG_COLUMNS, CONTRACT
from quote_desk.generate import synth_erp


@pytest.fixture(scope="module")
def scenario():
    clean = synth_erp.build_erp(seed=11, n_jobs=1500, messy=False)
    messy = synth_erp.build_erp(seed=11, n_jobs=1500, messy=True)
    return clean, messy, run(messy, CONTRACT)


def test_every_duplicate_part_is_merged_into_the_right_product(scenario):
    clean, messy, result = scenario
    truth_items = clean["items"].set_index("part_number")
    merged = result.crosswalk[result.crosswalk["key"] != result.crosswalk["master_key"]]
    messy_items = messy["items"].set_index("part_number")
    # Each merge joins two part numbers with the same configuration...
    for key, master in zip(merged["key"], merged["master_key"], strict=True):
        a = messy_items.loc[key, CONFIG_COLUMNS]
        b = messy_items.loc[master, CONFIG_COLUMNS]
        assert a.equals(b)  # .equals treats missing == missing
    # ...and after cleaning, exactly the true catalog's products remain.
    finished = result.tables["items"].query("item_type == 'finished'")
    assert len(finished) == (truth_items["item_type"] == "finished").sum()


def test_cost_history_is_exactly_the_completed_orders(scenario):
    clean, messy, result = scenario
    kept = set(result.datasets["cost_history"]["job_id"])
    truth_won = set(clean["jobs"].query("status == 'won'")["job_id"])
    cancelled = set(messy["jobs"].query("status == 'cancelled'")["job_id"])
    assert kept == truth_won - cancelled  # no quote copies, no partial costs
    assert not any(k.startswith("Q") for k in kept)


def test_unit_conversion_recovers_true_kg(scenario):
    clean, _, result = scenario
    cleaned = result.tables["boms"].set_index(["parent_part", "line_no"])["qty"]
    truth = clean["boms"].set_index(["parent_part", "line_no"])["qty"]
    both = cleaned.dropna().index.intersection(truth.index)
    assert len(both) > 0.9 * len(truth)
    assert (cleaned[both] - truth[both]).abs().max() < 0.01


def test_typos_are_caught_and_real_overruns_are_kept(scenario):
    clean, _, result = scenario
    history = result.datasets["cost_history"].set_index("job_id")
    truth = clean["jobs"].set_index("job_id")["actual_unit_cost"]
    ratio = history["actual_unit_cost"] / truth.reindex(history.index)
    typos = set(ratio[(ratio > 9) | (ratio < 0.12)].index)
    assert typos, "scenario should contain injected typos"

    review = set(result.review_queue.query("reason == 'extreme value'")["key"])
    recall = len(typos & review) / len(typos)
    precision = len(typos & review) / max(len(review), 1)
    assert recall == 1.0, f"missed typos: {typos - review}"
    assert precision >= 0.5, f"review queue too noisy: {review - typos}"

    # Every job stays in the history, typos included (flagged, not removed).
    assert typos <= set(history.index)
    overruns = clean["jobs"]["notes"].fillna("").str.startswith("major problem")
    overrun_ids = set(clean["jobs"][overruns]["job_id"]) & set(history.index)
    assert overrun_ids <= set(history.index)
    assert not (overrun_ids & review), "real overruns should not need a person"
