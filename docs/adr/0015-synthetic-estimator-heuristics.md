# 15. The synthetic estimator prices from human habits (pre-registered)

Status: Accepted (2026-11-24). Written before any re-measurement.

## Context
A check on the v1 generator showed the cost model does not beat the plant's estimators:
estimator-implied cost about 11-12% MAPE, LightGBM about 12%, oracle 9-12%. The reason
is that the synthetic estimator priced with the generator's own planned-cost formula plus
small noise, which makes it almost an oracle. No real estimator works that way. Changing
the estimator *after* seeing results would be tuning the comparison, so the rules are
fixed here first.

## Decision
The world's estimators price each request from these habits, each with a parameter drawn
once per estimator:
1. **Anchor:** start from the price of the most similar past job they quoted (same
   family, nearest size), scaled linearly by size.
2. **Stale metal:** metal prices are refreshed quarterly, not monthly.
3. **No learning curve:** the same unit price regardless of quantity, except a fixed
   discount bracket for 10+ units.
4. **Personal bias:** a multiplicative bias per estimator, lognormal with sigma 0.05.
5. **Workload noise:** noise sigma grows from 0.06 to 0.12 as the open-RFQ backlog rises.
6. **Rare options and engineering:** rare options and ETO engineering hours are
   under-estimated by 10-25%.

The pass band in `world check` is that the oracle's WAPE is at least 3 points below the
estimators' on the dev world. If the band fails, the miss is reported, and the habits
above are not tuned to pass it.

## Consequences
"Does it beat our estimators?" gets an honest, pre-committed test. The value claim
stays robust even if accuracy ties: seconds instead of days, a calibrated range, and
consistency across estimators.
