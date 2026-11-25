-- The event log (ADR 5): one ordered, append-only, hash-chained history of everything.
CREATE TABLE events (
    position   INTEGER PRIMARY KEY AUTOINCREMENT,  -- global order; also the live-stream id
    stream     TEXT NOT NULL,                      -- e.g. 'quote:Q-0001'
    stream_seq INTEGER NOT NULL,                   -- order within the stream
    type       TEXT NOT NULL,
    actor      TEXT NOT NULL,
    run_id     TEXT,
    causation  INTEGER REFERENCES events(position),
    sim_at     TEXT NOT NULL,                      -- simulated (business) time, ISO 8601
    wall_at    TEXT NOT NULL,                      -- real time, ISO 8601
    schema_v   INTEGER NOT NULL DEFAULT 1,
    payload    TEXT NOT NULL,                      -- JSON, validated by core/events.py
    prev_hash  TEXT NOT NULL,
    hash       TEXT NOT NULL UNIQUE,
    UNIQUE (stream, stream_seq)
);
CREATE INDEX events_by_run ON events(run_id);

-- Nobody may rewrite history: the database itself refuses.
CREATE TRIGGER events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
CREATE TRIGGER events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;

-- Background work (no broker): one worker claims one job at a time.
CREATE TABLE jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    kind            TEXT NOT NULL,
    payload         TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'queued',  -- queued | running | done | failed
    attempts        INTEGER NOT NULL DEFAULT 0,
    idempotency_key TEXT NOT NULL UNIQUE,
    error           TEXT
);

-- Emails waiting to be sent. A row can only exist for an approval event.
CREATE TABLE outbox (
    key               TEXT PRIMARY KEY,
    quote_id          TEXT NOT NULL,
    approval_position INTEGER NOT NULL REFERENCES events(position),
    recipient         TEXT NOT NULL,
    body              TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'staged'   -- staged | sent
);

-- Projections: screens built from events, updated in the same transaction.
CREATE TABLE inbox_items (
    quote_id      TEXT PRIMARY KEY,
    run_id        TEXT,
    customer      TEXT NOT NULL,
    summary       TEXT NOT NULL,
    total         REAL NOT NULL,
    bucket        TEXT NOT NULL,     -- ready | needs_senior | flagged | approved | rejected
    rule_ids      TEXT NOT NULL DEFAULT '[]',
    reasons       TEXT NOT NULL DEFAULT '[]',
    last_position INTEGER NOT NULL
);

CREATE TABLE runs (
    run_id        TEXT PRIMARY KEY,
    stream        TEXT NOT NULL,
    status        TEXT NOT NULL,     -- running | inbox | flagged | failed
    started_at    TEXT NOT NULL,
    last_position INTEGER NOT NULL
);

CREATE TABLE run_steps (
    run_id   TEXT NOT NULL,
    position INTEGER NOT NULL,
    step     TEXT NOT NULL,
    ok       INTEGER NOT NULL,
    detail   TEXT NOT NULL,
    seconds  REAL NOT NULL,
    PRIMARY KEY (run_id, position)
);

CREATE TABLE quote_view (
    quote_id TEXT PRIMARY KEY,
    data     TEXT NOT NULL             -- JSON: everything the quote detail page shows
);
