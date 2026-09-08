"""
conftest.py — Pytest fixtures for StudyLens AI tests.
Provides a Flask test client backed by an in-memory SQLite database.

Fix: init_db() is called INSIDE the pushed app context so that
the tables are created on the same flask.g connection that test
code will use via get_db(). Calling init_db() in a separate
with-block creates a throwaway connection that is immediately
discarded, leaving the test's connection empty.
"""
import os
import sys
import pathlib

# Set env vars BEFORE importing app so db.py and app.py see them
os.environ["DATABASE_URL"] = ":memory:"
os.environ.setdefault("JWT_SECRET", "test-secret-do-not-use-in-prod")
os.environ.setdefault("UPLOAD_ROOT", "/tmp/studylens_test_uploads")
os.environ.setdefault("GROQ_API_KEY", "test-key")
os.environ.setdefault("GROQ_MODEL", "test-model")

# Ensure the project root is on sys.path so `import app` works from tests/
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import pytest
from app import create_app
from db import init_db


@pytest.fixture(scope="function")
def flask_app():
    """Create a fresh Flask app with test config. Does NOT push a context."""
    app = create_app()
    app.config["TESTING"] = True
    app.config["DATABASE_URL"] = ":memory:"
    return app


@pytest.fixture(scope="function")
def app_ctx(flask_app):
    """Push an app context, initialise the DB schema, yield, then pop.

    init_db() is called HERE so tables are created on the flask.g
    connection that all subsequent get_db() calls within this context
    will reuse.
    """
    ctx = flask_app.app_context()
    ctx.push()
    init_db()          # ← tables created on the live g.db connection
    yield flask_app
    ctx.pop()


@pytest.fixture(scope="function")
def client(flask_app, app_ctx):
    """Return a test client.

    Depends on app_ctx so the schema is initialised before any request
    is made through the client.
    """
    return flask_app.test_client()
