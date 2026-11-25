# 5. SQLite app state: one global event log, projections and an outbox

Status: Accepted (2026-11-24, revised the same day for spec v3)

## Context
The approval inbox must answer "who decided what, when, under which rule". It must be
impossible to send an email without an approval. Several agents and the UI need one
ordered history to follow live. Traffic is tiny and local.

## Decision
- SQLite (WAL, foreign keys on), raw `sqlite3`, numbered SQL migrations tracked with
  `PRAGMA user_version`.
- One `events` table for everything: a global `position` (also the SSE id), a per-stream
  `stream_seq` (optimistic concurrency), the actor, the run id, the causing event, the
  simulated and real time, a typed payload, and `prev_hash` / `hash`.
- Triggers block UPDATE and DELETE. `audit verify` checks the chain. Chain-head
  checkpoints are written outside the database, so rewriting the whole chain is detected.
- Projections (inbox, quote view, runs, metrics, sources) are updated in the same
  transaction as the events. `rebuild-projections` replays the log, and a test checks
  rebuild == live.
- Emails go to an `outbox` table that only a fresh approval event can fill. The sender
  re-checks a facts hash and the policy version, and the mailer drops duplicates.
- A `jobs` table with one asyncio worker runs background work. There is no broker.

## Consequences
A tamper-evident, replayable record with no extra infrastructure. Single writer by
design. If it ever needs to scale, the path is Postgres with `LISTEN/NOTIFY` and a
workflow engine, as named in ADR 13.
