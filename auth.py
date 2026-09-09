import os
import re
import uuid
import datetime
import functools

import jwt
from flask import request, jsonify, g
from flask_bcrypt import Bcrypt

from db import get_db

bcrypt = Bcrypt()


# ---------------------------------------------------------------------------
# Exception classes
# ---------------------------------------------------------------------------

class ValidationError(Exception):
    """Raised when request input fails validation. Maps to HTTP 400."""
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message
        self.status_code = 400


class ConflictError(Exception):
    """Raised when a unique constraint is violated. Maps to HTTP 409."""
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message
        self.status_code = 409


class AuthError(Exception):
    """Raised when authentication fails. Maps to HTTP 401."""
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message
        self.status_code = 401


# ---------------------------------------------------------------------------
# Task 3.1 — register
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

# bcrypt has a hard 72-byte limit; passwords are truncated to this length
# before hashing so the validation window (8-128 chars) remains intact.
_BCRYPT_MAX_BYTES = 72


def _bcrypt_password(password: str) -> bytes:
    """Return UTF-8 encoded password truncated to bcrypt's 72-byte limit."""
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def register(email: str, password: str) -> None:
    """Register a new user with the given email and password.

    Validates the email format and password length, checks for duplicate
    emails, hashes the password with bcrypt (12 rounds), and inserts the
    new user record into the database.

    Raises:
        ValidationError: If the email format is invalid or the password
            length is outside [8, 128].
        ConflictError: If the email is already registered.
    """
    # 1. Email validation
    if not _EMAIL_RE.match(email):
        raise ValidationError("Invalid email format.")

    # 2. Password length validation
    if len(password) < 8 or len(password) > 128:
        raise ValidationError("Password must be between 8 and 128 characters.")

    db = get_db()

    # 3. Duplicate email check
    row = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if row is not None:
        raise ConflictError("Email already registered.")

    # 4. Hash password — truncate to 72 bytes before bcrypt
    password_hash = bcrypt.generate_password_hash(
        _bcrypt_password(password), rounds=12
    ).decode("utf-8")

    # 5. Insert user
    user_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO users (id, email, password_hash) VALUES (?, ?, ?)",
        (user_id, email, password_hash),
    )
    db.commit()


# ---------------------------------------------------------------------------
# Task 3.2 — login
# ---------------------------------------------------------------------------

def login(email: str, password: str) -> str:
    """Authenticate a user and return a signed JWT access token.

    Looks up the user by email, verifies the password using bcrypt, and
    returns a JWT valid for 24 hours signed with ``JWT_SECRET``.

    Raises:
        AuthError: If the email is not found or the password is incorrect.
            Both cases surface the same message to avoid user enumeration.
    """
    db = get_db()

    # 1. Look up user
    row = db.execute(
        "SELECT id, password_hash FROM users WHERE email = ?", (email,)
    ).fetchone()
    if row is None:
        raise AuthError("Invalid credentials.")

    user_id: str = row["id"]
    stored_hash: str = row["password_hash"]

    # 2. Verify password — truncate to 72 bytes to match registration hashing
    if not bcrypt.check_password_hash(stored_hash, _bcrypt_password(password)):
        raise AuthError("Invalid credentials.")

    # 3. Build JWT
    secret = os.environ.get("JWT_SECRET", "dev-secret-change-me")
    now = int(datetime.datetime.utcnow().timestamp())
    payload = {"sub": user_id, "iat": now, "exp": now + 86400}
    token = jwt.encode(payload, secret, algorithm="HS256")

    # PyJWT < 2.0 returns bytes; >= 2.0 returns str
    if isinstance(token, bytes):
        token = token.decode("utf-8")

    return token


# ---------------------------------------------------------------------------
# Task 3.3 — require_auth decorator
# ---------------------------------------------------------------------------

def require_auth(f):
    """Flask route decorator that enforces JWT bearer-token authentication.

    Reads the ``Authorization`` header, validates the bearer token, and
    stores the authenticated user''s ID in ``flask.g.current_user`` before
    delegating to the wrapped view function.

    Returns HTTP 401 JSON responses for missing/invalid tokens and for
    expired sessions.
    """
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        header = request.headers.get("Authorization", "")

        # 2-3. Check header presence and format
        if not header or not header.startswith("Bearer "):
            return jsonify({"error": "Authentication required"}), 401

        # 4. Extract token
        token = header.split(" ", 1)[1]

        secret = os.environ.get("JWT_SECRET", "dev-secret-change-me")

        # 5-7. Decode and handle errors
        try:
            payload = jwt.decode(token, secret, algorithms=["HS256"])
        except jwt.exceptions.ExpiredSignatureError:
            return jsonify({"error": "Session expired"}), 401
        except Exception:
            return jsonify({"error": "Authentication required"}), 401

        # 8. Attach user and call the wrapped function
        g.current_user = payload["sub"]
        return f(*args, **kwargs)

    return decorated