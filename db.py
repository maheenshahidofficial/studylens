"""
db.py -- Database abstraction for StudyLens AI.

Local development:  SQLite (DATABASE_URL is a file path, e.g. "studylens.db")
Production (Vercel): PostgreSQL via psycopg2 (DATABASE_URL is a postgres:// URI)

Detection: if DATABASE_URL starts with "postgres" -> use PostgreSQL, else SQLite.

All SQL uses %s placeholders when in PostgreSQL mode and ? when in SQLite mode
so that the same query strings can be adapted at runtime via _p().
"""
import sqlite3
import os
import logging

from flask import g

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers: detect backend and normalise placeholders
# ---------------------------------------------------------------------------

def _db_url() -> str:
    return os.environ.get("DATABASE_URL", "studylens.db")


def _is_postgres() -> bool:
    url = _db_url()
    return url.startswith("postgres://") or url.startswith("postgresql://")


def _p(sql: str) -> str:
    """Convert SQLite ? placeholders to psycopg2 %s when using Postgres."""
    if _is_postgres():
        return sql.replace("?", "%s")
    return sql


# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------

def get_db():
    """Return the database connection for the current request context.

    Stored on Flask g so it is reused within a request and closed on teardown.
    Returns a psycopg2 connection (Postgres) or sqlite3 connection (SQLite).
    Both expose a .execute() interface; sqlite3.Row-style column access is
    normalised by the DictCursor wrapper for Postgres.
    """
    if "db" not in g:
        url = _db_url()
        if _is_postgres():
            import psycopg2
            import psycopg2.extras
            conn = psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)
            conn.autocommit = False
            g.db = _PgConnection(conn)
        else:
            conn = sqlite3.connect(url)
            conn.row_factory = sqlite3.Row
            g.db = _SqliteConnection(conn)
    return g.db


def close_db(exception=None) -> None:
    """Close the database connection at the end of a request context."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


# ---------------------------------------------------------------------------
# Thin wrappers that give both backends the same .execute() / .commit() API
# ---------------------------------------------------------------------------

class _SqliteConnection:
    """Wraps a sqlite3 connection to match the interface used throughout the app."""

    def __init__(self, conn):
        self._conn = conn
        # Expose row_factory so existing code that sets it still works
        self.row_factory = conn.row_factory

    def execute(self, sql, params=()):
        return self._conn.execute(_p(sql), params)

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


class _PgConnection:
    """Wraps a psycopg2 connection to match the sqlite3-style interface used in the app.

    psycopg2 uses cursors; we keep a single persistent cursor per connection
    and return it from execute() so callers can call .fetchone()/.fetchall() on it.
    """

    def __init__(self, conn):
        self._conn = conn
        self._cursor = conn.cursor()

    def execute(self, sql, params=()):
        # Convert empty tuple to None for psycopg2 compatibility
        self._cursor.execute(_p(sql), params if params else None)
        return self._cursor

    def commit(self):
        self._conn.commit()

    def close(self):
        try:
            self._cursor.close()
        except Exception:
            pass
        try:
            self._conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Schema initialisation — safe to run repeatedly (CREATE TABLE IF NOT EXISTS)
# ---------------------------------------------------------------------------

_SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS analysis_sessions (
    id                    TEXT PRIMARY KEY,
    student_id            TEXT NOT NULL REFERENCES users(id),
    course_name           TEXT,
    status                TEXT NOT NULL DEFAULT 'pending',
    failure_reason        TEXT,
    created_at            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at          DATETIME,
    readiness_score       INTEGER,
    coverage_summary_json TEXT,
    full_report_json      TEXT,
    revision_plan_json    TEXT
);

CREATE TABLE IF NOT EXISTS extracted_texts (
    id         TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES analysis_sessions(id),
    doc_type   TEXT NOT NULL,
    content    TEXT NOT NULL,
    char_count INTEGER NOT NULL,
    warnings   TEXT
);

CREATE TABLE IF NOT EXISTS session_artifacts (
    id            TEXT PRIMARY KEY,
    session_id    TEXT NOT NULL REFERENCES analysis_sessions(id),
    artifact_type TEXT NOT NULL,
    payload_json  TEXT NOT NULL,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tutor_messages (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES analysis_sessions(id),
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

_SCHEMA_POSTGRES = """
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS analysis_sessions (
    id                    TEXT PRIMARY KEY,
    student_id            TEXT NOT NULL REFERENCES users(id),
    course_name           TEXT,
    status                TEXT NOT NULL DEFAULT 'pending',
    failure_reason        TEXT,
    created_at            TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at          TIMESTAMP,
    readiness_score       INTEGER,
    coverage_summary_json TEXT,
    full_report_json      TEXT,
    revision_plan_json    TEXT
);

CREATE TABLE IF NOT EXISTS extracted_texts (
    id         TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES analysis_sessions(id),
    doc_type   TEXT NOT NULL,
    content    TEXT NOT NULL,
    char_count INTEGER NOT NULL,
    warnings   TEXT
);

CREATE TABLE IF NOT EXISTS session_artifacts (
    id            TEXT PRIMARY KEY,
    session_id    TEXT NOT NULL REFERENCES analysis_sessions(id),
    artifact_type TEXT NOT NULL,
    payload_json  TEXT NOT NULL,
    created_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tutor_messages (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES analysis_sessions(id),
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);
"""


def init_db() -> None:
    """Create all tables if they do not already exist.

    Safe to call on every application start -- uses CREATE TABLE IF NOT EXISTS.
    On Postgres, runs each statement individually (psycopg2 does not support
    multi-statement strings).
    """
    db = get_db()

    if _is_postgres():
        statements = [
            s.strip() for s in _SCHEMA_POSTGRES.split(";")
            if s.strip() and not s.strip().startswith("--")
        ]
        for stmt in statements:
            db.execute(stmt)
        db.commit()
    else:
        # SQLite: execute the whole block at once via executescript
        conn = db._conn  # unwrap to raw sqlite3 connection
        conn.executescript(_SCHEMA_SQLITE)
        conn.commit()


# ---------------------------------------------------------------------------
# Tutor message helpers (used by tutor.py)
# ---------------------------------------------------------------------------

def get_tutor_messages(session_id: str, limit: int = 10) -> list:
    """Return the most recent N tutor messages for a session in chronological ASC order."""
    db = get_db()
    rows = db.execute(
        """SELECT id, session_id, role, content, created_at
           FROM tutor_messages
           WHERE session_id = ?
           ORDER BY created_at DESC
           LIMIT ?""",
        (session_id, limit),
    ).fetchall()
    # Reverse so the result is chronological ASC (oldest first)
    if _is_postgres():
        return list(reversed([dict(r) for r in rows]))
    return list(reversed(rows))


def save_tutor_message(session_id: str, role: str, content: str) -> str:
    """Insert a tutor message and return the generated UUID."""
    import uuid as _uuid
    message_id = str(_uuid.uuid4())
    db = get_db()
    db.execute(
        """INSERT INTO tutor_messages (id, session_id, role, content)
           VALUES (?, ?, ?, ?)""",
        (message_id, session_id, role, content),
    )
    db.commit()
    return message_id


def count_tutor_messages(session_id: str) -> int:
    """Return the total number of tutor messages stored for a session."""
    db = get_db()
    row = db.execute(
        "SELECT COUNT(*) AS cnt FROM tutor_messages WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        return 0
    # Postgres RealDictCursor returns dict-like; sqlite3.Row also supports key access
    if _is_postgres():
        return dict(row).get("cnt", 0)
    return row["cnt"]