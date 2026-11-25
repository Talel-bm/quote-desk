# 6. Forge: ratio-to-should-cost target, global model, conformal ranges

Status: Accepted (2026-11-24)

## Context
Copper rises about 77% over the history, and tree models cannot predict beyond prices
they have seen. Raw quantile models give ranges with no coverage guarantee. Product
families differ in how much history they have.

## Decision
- Compute should-cost from ERP planning data (BOM quantities x price known before the
  quote date, plus routing hours x labor rate) and predict log(actual / should-cost).
- One global LightGBM (P10/P50/P90) with family as a feature, not one model per family.
- Calibrate ranges with conformalized quantile regression on the most recent slice;
  sort quantiles to avoid crossing.
- Evaluate with a rolling-origin backtest against a ladder of baselines; report
  coverage together with width; promote a model only through a gate test.

## Consequences
Price moves are handled by should-cost, which also makes repricing cheap. Coverage is
an average guarantee; per-family calibration and adaptive conformal come in M7.
