# 14. Authority policy: permit/forbid rules with citations, tiers and presets

Status: Accepted (2026-11-24)

## Context
Approval rules must be data that can be reviewed, simulated and cited, not code paths.
"Needs senior approval" had been modeled as a third outcome, which made the semantics
unclear.

## Decision
- **Rules file.** `policy/authority.yaml` holds rules with `id`, `effect` (permit or
  forbid), `principal`, `action`, a `when` list over a closed set of operators (nothing is
  evaluated as code), and `source`, a section of a written pricing-authority memo.
- **Evaluation.** Default deny; any matching forbid wins (Cedar semantics). "Needs
  senior" means only seniors are permitted to approve.
- **Tiers and presets.** Actions are tiered info / commit / commercial / financial.
  Presets cautious / balanced / autonomous change only what is permitted. Financial
  actions, such as payment-detail changes, are forbidden in every preset. Agents can
  never approve a send.
- **Recording.** Every decision records its rule ids, citations and policy version.
- **Simulation.** `policy simulate` re-decides past decisions under a candidate policy
  and lists what would change.

## Consequences
Each policy outcome can be explained by its rule and source. Changes are previewed before
approval. Properties (forbid wins, default deny) are tested with Hypothesis.
