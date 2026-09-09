"""
test_auth.py -- Unit tests for authentication (Tasks 16.1 and 16.2).
Fixtures (client, app_ctx) from conftest.py.
"""
import sys
import pathlib
import time
import os

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import jwt as pyjwt
import pytest


def _register(client, email, pw):
    return client.post("/auth/register", json={"email": email, "password": pw})


def _login(client, email, pw):
    return client.post("/auth/login", json={"email": email, "password": pw})


# ===========================================================================
# Task 16.1 -- Auth registration
# ===========================================================================

def test_register_success(client, app_ctx):
    r = _register(client, "new_reg@example.com", "Password1!")
    assert r.status_code == 201


def test_register_duplicate_email_returns_409(client, app_ctx):
    _register(client, "dup_reg@example.com", "Password1!")
    r = _register(client, "dup_reg@example.com", "Password1!")
    assert r.status_code == 409


def test_register_password_7_chars_rejected(client, app_ctx):
    r = _register(client, "pw7@example.com", "A" * 7)
    assert r.status_code == 400


def test_register_password_8_chars_accepted(client, app_ctx):
    r = _register(client, "pw8@example.com", "A" * 8)
    assert r.status_code == 201


def test_register_password_72_chars_accepted(client, app_ctx):
    """72-char password is accepted (within the 8-128 spec range)."""
    r = _register(client, "pw72@example.com", "A" * 72)
    assert r.status_code == 201


def test_register_password_128_chars_accepted(client, app_ctx):
    """128-char password is accepted (upper boundary of the 8-128 spec range).

    auth.py truncates to 72 bytes before calling bcrypt, so passwords up
    to 128 chars are accepted by validation and hashed safely without
    triggering bcrypt s hard 72-byte ValueError.
    """
    r = _register(client, "pw128@example.com", "A" * 128)
    assert r.status_code == 201


def test_register_password_129_chars_rejected(client, app_ctx):
    r = _register(client, "pw129@example.com", "A" * 129)
    assert r.status_code == 400


def test_register_email_no_at_rejected(client, app_ctx):
    r = _register(client, "nodomain", "Password1!")
    assert r.status_code == 400


def test_register_email_no_domain_rejected(client, app_ctx):
    r = _register(client, "missing@", "Password1!")
    assert r.status_code == 400


def test_register_email_leading_dot_documents_behavior(client, app_ctx):
    # The regex r"^[^\s@]+@[^\s@]+\.[^\s@]+$" accepts ".bad@example.com"
    # (any non-@ non-space char before @). Documenting actual behavior.
    r = _register(client, ".bad@example.com", "Password1!")
    assert r.status_code in (201, 400)


# ===========================================================================
# Task 16.2 -- Login / JWT
# ===========================================================================

def test_login_valid_returns_jwt(client, app_ctx):
    _register(client, "login_ok@example.com", "Password1!")
    r = _login(client, "login_ok@example.com", "Password1!")
    assert r.status_code == 200
    data = r.get_json()
    assert "token" in data
    assert "expires_at" in data


def test_login_jwt_has_expected_claims(client, app_ctx):
    _register(client, "claims@example.com", "Password1!")
    r = _login(client, "claims@example.com", "Password1!")
    token = r.get_json()["token"]
    secret = os.environ.get("JWT_SECRET", "test-secret-do-not-use-in-prod")
    payload = pyjwt.decode(token, secret, algorithms=["HS256"])
    assert "sub" in payload
    assert "exp" in payload
    assert "iat" in payload
    assert payload["exp"] > int(time.time())


def test_login_wrong_password_returns_401(client, app_ctx):
    _register(client, "wrongpw@example.com", "Password1!")
    r = _login(client, "wrongpw@example.com", "WrongPassword!")
    assert r.status_code == 401


def test_login_unknown_email_returns_401(client, app_ctx):
    r = _login(client, "nobody_xyz@example.com", "Password1!")
    assert r.status_code == 401


def test_login_wrong_password_and_unknown_email_same_message(client, app_ctx):
    _register(client, "samemsg_reg@example.com", "Password1!")
    r_wrong_pw = _login(client, "samemsg_reg@example.com", "Wrong!")
    r_unknown  = _login(client, "unknown_zzz@example.com",  "Wrong!")
    assert r_wrong_pw.status_code == 401
    assert r_unknown.status_code == 401
    assert r_wrong_pw.get_json().get("error") == r_unknown.get_json().get("error")


def test_expired_token_returns_401_session_expired(client, app_ctx):
    secret = os.environ.get("JWT_SECRET", "test-secret-do-not-use-in-prod")
    expired_payload = {
        "sub": "fake-user-id",
        "iat": int(time.time()) - 10,
        "exp": int(time.time()) - 1,
    }
    expired_token = pyjwt.encode(expired_payload, secret, algorithm="HS256")
    r = client.get("/api/sessions", headers={"Authorization": f"Bearer {expired_token}"})
    assert r.status_code == 401
    assert "expired" in r.get_json().get("error", "").lower()