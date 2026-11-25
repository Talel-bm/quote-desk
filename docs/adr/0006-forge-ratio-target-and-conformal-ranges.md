# 6. Forge: ratio-to-should-cost target, global model, conformal ranges, honest backtest

Status: Accepted (2026-11-24, revised the same day for spec v3)

## Context
Copper rises about 77% over the history, and tree models cannot predict beyond prices
they have seen. Raw quantile models give ranges with no coverage guarantee. Families
differ in how much history they have, and the acquired plant has little. A job's actual
cost is known only when it ships, 1-3 months after the quote.

## Decision
- **Target.** Compute should-cost from planning data: BOM quantities, or quantities
  learned from the item master for new configurations, times prices published before the
  quote date, plus hours times labor rate. Predict log(actual / should-cost). The model
  sees the copper trend, not the copper level, so a copper scenario is not counted twice.
- **Model.** One global LightGBM (P10/P50/P90) with family as a feature. Ranges are
  conformalized per family where there are enough rows, shrunk toward the group
  otherwise. Quantiles are sorted so they never cross.
- **Backtest.** Rolling origin, training only on jobs *shipped* before each cut-off.
  Outlier flags are recomputed inside each window, and no after-the-fact columns are used.
- **Baselines.** The ladder includes the estimators' implied cost and the generator
  oracle (evals only).
- **Gates.** Promotion and pass rules use paired block-bootstrap CIs, not fixed point
  bands, because the samples are small.
- **Abstain.** Requests outside the training data return "needs an estimator".

## Consequences
Price moves are handled by should-cost, which also makes repricing cheap. Coverage is an
average guarantee, so per-family and per-configuration coverage are measured separately.
Online conformal through drift is on the roadmap.
