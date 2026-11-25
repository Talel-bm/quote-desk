# 3. A hand-built causal world simulator with hidden ground truth

Status: Accepted (2026-11-24)

## Context
There is no real company data. Statistical synthesizers (SDV, CTGAN) copy an existing
dataset and produce no answer key, so nothing could be scored.

## Decision
Keep a hand-written simulator (as Synthea does for health records): plants, products,
customers, quotes, jobs and documents, driven by real public price series. It writes
the messy sources plus a hidden truth folder: error ledger, true cross-plant links,
true cost drivers. Only `evals/` and tests read the truth.

## Consequences
Every layer can be scored against exact answers (cleaning per error kind, matching F1,
extraction accuracy, interval coverage per configuration). The limitation that the
author knows the generator is stated openly and mitigated by import rules and
learnability checks.
