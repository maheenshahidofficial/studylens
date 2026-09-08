import sqlite3
import os

from flask import g


def get_db() -> sqlite3.Connection:
    """Return the SQLite connection for the current request context.

    The connection is opened once per request and stored on Flask's ``g``
    object so subsequent calls within the same request context reuse it.
    The database path is read from the ``DATABASE_URL`` environment variable
    and falls back to ``"studylens.db"`` when the variable is unset.
    ``row_factory`` is set to ``sqlite3.Row`` so columns are accessible by
    name as well as index.
    """
    if "db" not in g:
        db_path = os.environ.get("DATABASE_URL", "studylens.db")
        g.db = sqlite3.connect(db_path)
        g.db.row_factory = sqlite3.Row
    return g.db


def init_db() -> None:
    """Create all four application tables if they do not already exist.

    Calls ``get_db()`` to obtain the current connection, executes the full
    schema DDL, and commits the transaction.
    """
    db = get_db()

    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            TEXT PRIMARY KEY,
            email         TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    db.execute("""
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
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS extracted_texts (
            id         TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES analysis_sessions(id),
            doc_type   TEXT NOT NULL,
            content    TEXT NOT NULL,
            char_count INTEGER NOT NULL,
            warnings   TEXT
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS session_artifacts (
            id            TEXT PRIMARY KEY,
            session_id    TEXT NOT NULL REFERENCES analysis_sessions(id),
            artifact_type TEXT NOT NULL,
            payload_json  TEXT NOT NULL,
            created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS tutor_messages (
            id          TEXT PRIMARY KEY,
            session_id  TEXT NOT NULL REFERENCES analysis_sessions(id),
            role        TEXT NOT NULL,
            content     TEXT NOT NULL,
            created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    db.commit()


def close_db(exception=None) -> None:
    """Close the SQLite connection at the end of a request context.

    Pops ``db`` from Flask's ``g`` object and closes it.  Intended to be
    registered with ``app.teardown_appcontext(close_db)``.
    """
    db = g.pop("db", None)
    if db is not None:
        db.close()


def get_tutor_messages(session_id: str, limit: int = 10) -> list:
    """Return the most recent N tutor messages for a session in chronological ASC order.

    Args:
        session_id: The analysis session UUID.
        limit:      Maximum number of messages to return (default 10).

    Returns:
        List of sqlite3.Row objects ordered by created_at ASC.
    """
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
    return list(reversed(rows))


def save_tutor_message(session_id: str, role: str, content: str) -> str:
    """Insert a tutor message and return the generated UUID.

    Args:
        session_id: The analysis session UUID.
        role:       'user' or 'assistant'.
        content:    The message text.

    Returns:
        The UUID string of the newly created row.
    """
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
    """Return the total number of tutor messages stored for a session.

    Args:
        session_id: The analysis session UUID.

    Returns:
        Integer count of rows in tutor_messages for this session.
    """
    db = get_db()
    row = db.execute(
        "SELECT COUNT(*) AS cnt FROM tutor_messages WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    return row["cnt"] if row else 0
