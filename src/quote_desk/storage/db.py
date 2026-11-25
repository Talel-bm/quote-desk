"""Opening app.sqlite and applying migrations.

Migrations are numbered SQL files in `storage/migrations/` (001_*.sql, 002_*.sql, ...).
SQLite's `PRAGMA user_version` remembers the last one applied, so `connect()` applies
only the new ones. No migration framework is needed for this (ADR 5).
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# Importing projections registers the projector functions that append() runs.
import quote_desk.storage.projections  # noqa: F401

MIGRATIONS = Path(__file__).parent / "migrations"


def migration_files() -> list[tuple[int, Path]]:
    """All migration files with their number, in order."""
    files = sorted(MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql"))
    return [(int(f.name[:3]), f) for f in files]


def migrate(conn: sqlite3.Connection) -> int:
    """Apply migrations newer than the database's user_version; return the new version."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for number, path in migration_files():
        if number > current:
            conn.executescript(
                "BEGIN;\n"
                + path.read_text(encoding="utf-8")
                + f"\nPRAGMA user_version = {number};\nCOMMIT;"
            )
            current = number
    return int(current)


def connect(path: Path | str) -> sqlite3.Connection:
    """Open (or create) the app database, configured and fully migrated.

    `isolation_level=None` means Python never starts transactions on its own: we open
    them explicitly with `transaction()`, so we always know what is committed together.
    """
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")  # readers don't block the writer
    migrate(conn)
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run a block as one transaction: all of it is saved, or none of it.

    BEGIN IMMEDIATE takes the write lock at the start, so two writers can never
    interleave inside a transaction.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
