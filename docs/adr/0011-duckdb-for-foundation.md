# 11. DuckDB for Foundation, SQLite for the app

Status: Accepted (2026-11-24)

## Context
Foundation's work is analytical: matching joins, metric history across deliveries, reads
from several formats, and merges. The app's work is transactional: many small writes,
append-only triggers and a single writer.

## Decision
Foundation writes `foundation.duckdb`. The pandas cleaning code stays as it is; only the
storage module changes. `app.sqlite` stays SQLite (ADR 5). The DuckDB version is pinned
with `uv add` and recorded here when it is added.

## Consequences
Two embedded engines, each used for what it is good at, with no server. Forge reads
training data from DuckDB through `foundation/query.py`.
