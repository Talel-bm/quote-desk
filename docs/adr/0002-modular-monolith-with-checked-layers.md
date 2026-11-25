# 2. Modular monolith with layers checked in CI

Status: Accepted (2026-11-24)

## Context
Six concerns (data, models, intake, agents, API, UI) live in one small codebase.
Splitting into services would add deployment work with no benefit at this size, but
without rules a monolith slowly becomes tangled.

## Decision
One package, layered as in `docs/architecture.md`. `import-linter` enforces: higher
layers import lower ones only; `intake` and `forge` are independent; no product
package imports `quote_desk.generate`. Protocols (ports) only at real seams
(LLM, source readers, clock, mailer), each with a fake.

## Consequences
The rule "the cost model never sees the generator's formulas" becomes a failing CI
check instead of a promise. Adding a layer means updating the import-linter config.
