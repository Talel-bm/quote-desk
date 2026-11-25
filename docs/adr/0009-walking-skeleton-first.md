# 9. Walking skeleton before depth

Status: Accepted (2026-11-24)

## Context
Steps 1-2 deepened the data layers one at a time. The remaining layers (models,
intake, agents, API, UI, deployment) have never run together, and a fixed deadline
(2026-12-02) requires something demonstrable end to end.

## Decision
Build the thinnest working version of every layer, connected and deployed (Step 3), then
deepen one layer per milestone. Each later milestone improves something already
visible in the running app.

## Consequences
Integration and deployment problems appear on day 2, not day 20. Early versions are
crude (the first cost model is a baseline) and some code is rewritten later.
