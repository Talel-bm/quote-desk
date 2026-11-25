# 5. SQLite app state: append-only event log and outbox

Status: Accepted (2026-11-24)

## Context
The approval inbox must answer "who decided what, when, under which rule", and it
must be impossible to send an email without an approval. Traffic is tiny and local.

## Decision
SQLite (WAL, foreign keys on), raw `sqlite3`, numbered SQL migrations tracked with
`PRAGMA user_version`. An `events` table is append-only (triggers block UPDATE and
DELETE) and hash-chained (each row stores the hash of the previous one);
`quote-desk verify-audit` checks the chain. A `quotes` table holds current state and
is written in the same transaction. Emails go to an `outbox` table that only an
approval event can fill; the sender tolerates duplicates.

## Consequences
A tamper-evident record of actions with no extra infrastructure. Postgres, an ORM and
a message broker are named as the scale-up path, not used.
