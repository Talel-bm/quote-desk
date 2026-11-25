# 16. Evidence protocol: pre-registration, a sealed world, CIs and M/D/P labels

Status: Accepted (2026-11-24)

## Context
The author wrote the world, the models and the evals. Without discipline, every number
could be tuned to look good. Sample sizes are small enough that point estimates mislead.

## Decision
- **Pre-registration.** `evals/preregistration.yaml` lists, per layer, the primary
  metric, the comparison, the pass rule, n and the CI method. It is committed before
  measured runs. A changed rule is a new commit with a reason, and reports show both.
- **Sealed world.**
  - The final world uses a different seed and a perturbation profile chosen by a separate
    agent from a documented menu: noise level, option rarity, copper path, estimator bias.
  - Its hash is committed before the freeze tag, and it is opened once.
  - The intake held-out set is written by independent agents and frozen the same way.
- **Statistics.** Block bootstrap by month for Forge, clustering by document for Intake,
  and paired comparisons between systems.
- **Labels.** Every number is a `Metric(value, ci_low, ci_high, n, label, source)` with
  label Measured, Derived or Projected. Simulated-approver metrics say "Measured in
  simulation".
- **One source of results.** The README results block and the Evidence page are generated
  from `evals/results.json` only.

## Consequences
Some pre-registered criteria may fail. They are reported as failures with their numbers.
