"""
test_endpoints.py — Tutor endpoint tests for StudyLens AI.

Tests the POST /api/tutor/chat endpoint with mocked AI so no real API
calls are made. Also verifies that existing auth/analysis endpoints
remain intact.

Fixtures (client, app_ctx) are provided by conftest.py.
"""
import sys
import pathlib
import uuid
import datetime as dt
import json
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _register_and_login(client, email, pw="Password123!"):
    client.post("/auth/register", json={"email": email, "password": pw})
    r = client.post("/auth/login", json={"email": email, "password": pw})
    data = r.get_json()
    assert "token" in data, f"Login failed: {data}"
    return data["token"]


def _auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def _create_complete_session(app_ctx, student_email):
    """Insert a complete analysis session for the given student and return session_id."""
    from db import get_db
    db = get_db()
    user = db.execute("SELECT id FROM users WHERE email = ?", (student_email,)).fetchone()
    session_id = str(uuid.uuid4())
    full_report = json.dumps({
        "topics": [{"title": "OOP", "importance": "high", "coverage_status": "covered",
                    "reasoning": "Well covered.", "key_gaps": []}],
        "readiness_score": 80,
        "coverage_summary": {"total": 1, "covered": 1, "partially_covered": 0, "missing": 0},
        "knowledge_gaps": [],
        "warnings": [],
    })
    revision_plan = json.dumps({"tasks": [], "total_minutes": 0})
    db.execute(
        """INSERT INTO analysis_sessions
           (id, student_id, status, created_at, readiness_score,
            coverage_summary_json, full_report_json, revision_plan_json)
           VALUES (?, ?, 'complete', ?, 80, ?, ?, ?)""",
        (session_id, user["id"], dt.datetime.utcnow().isoformat(),
         json.dumps({"total": 1, "covered": 1, "partially_covered": 0, "missing": 0}),
         full_report, revision_plan),
    )
    db.execute(
        """INSERT INTO extracted_texts (id, session_id, doc_type, content, char_count)
           VALUES (?, ?, 'study_material', 'Test study material about OOP concepts.', 40)""",
        (str(uuid.uuid4()), session_id),
    )
    db.execute(
        """INSERT INTO extracted_texts (id, session_id, doc_type, content, char_count)
           VALUES (?, ?, 'syllabus', 'OOP, Inheritance, Polymorphism.', 32)""",
        (str(uuid.uuid4()), session_id),
    )
    db.commit()
    return session_id


# ---------------------------------------------------------------------------
# Mock helper
# ---------------------------------------------------------------------------

def _mock_groq_response(text="This is the tutor response."):
    """Build a minimal mock that makes openai.OpenAI().chat.completions.create() work."""
    mock_choice = MagicMock()
    mock_choice.message.content = text
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response

    mock_openai_cls = MagicMock(return_value=mock_client)
    return mock_openai_cls, mock_client


# ---------------------------------------------------------------------------
# 1. Valid tutor request
# ---------------------------------------------------------------------------

def test_tutor_chat_valid_request(client, app_ctx):
    token = _register_and_login(client, "tutor_valid@example.com")
    session_id = _create_complete_session(app_ctx, "tutor_valid@example.com")

    mock_cls, _ = _mock_groq_response("Polymorphism means many forms.")
    with patch("tutor.openai.OpenAI", mock_cls):
        resp = client.post(
            "/api/tutor/chat",
            json={"message": "What is polymorphism?", "session_id": session_id},
            headers=_auth_headers(token),
        )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "response" in data
    assert len(data["response"]) > 0


# ---------------------------------------------------------------------------
# 2. Empty message
# ---------------------------------------------------------------------------

def test_tutor_chat_empty_message(client, app_ctx):
    token = _register_and_login(client, "tutor_empty@example.com")
    session_id = _create_complete_session(app_ctx, "tutor_empty@example.com")

    resp = client.post(
        "/api/tutor/chat",
        json={"message": "   ", "session_id": session_id},
        headers=_auth_headers(token),
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "message" in data["error"].lower() or "empty" in data["error"].lower()


# ---------------------------------------------------------------------------
# 3. Missing message field
# ---------------------------------------------------------------------------

def test_tutor_chat_missing_message(client, app_ctx):
    token = _register_and_login(client, "tutor_missing@example.com")
    session_id = _create_complete_session(app_ctx, "tutor_missing@example.com")

    resp = client.post(
        "/api/tutor/chat",
        json={"session_id": session_id},
        headers=_auth_headers(token),
    )
    assert resp.status_code == 400
    assert resp.get_json()["success"] is False


# ---------------------------------------------------------------------------
# 4. Invalid / non-JSON body
# ---------------------------------------------------------------------------

def test_tutor_chat_invalid_json(client, app_ctx):
    token = _register_and_login(client, "tutor_json@example.com")

    resp = client.post(
        "/api/tutor/chat",
        data="not-valid-json",
        content_type="application/json",
        headers=_auth_headers(token),
    )
    assert resp.status_code == 400
    assert resp.get_json()["success"] is False


# ---------------------------------------------------------------------------
# 5. Unauthorized request (no token)
# ---------------------------------------------------------------------------

def test_tutor_chat_unauthorized(client, app_ctx):
    resp = client.post(
        "/api/tutor/chat",
        json={"message": "Hello", "session_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 6. Non-existent session
# ---------------------------------------------------------------------------

def test_tutor_chat_nonexistent_session(client, app_ctx):
    token = _register_and_login(client, "tutor_noexist@example.com")
    fake_id = str(uuid.uuid4())

    resp = client.post(
        "/api/tutor/chat",
        json={"message": "Hello", "session_id": fake_id},
        headers=_auth_headers(token),
    )
    assert resp.status_code == 404
    assert resp.get_json()["success"] is False


# ---------------------------------------------------------------------------
# 7. Another student's session (ownership check)
# ---------------------------------------------------------------------------

def test_tutor_chat_cross_student_access(client, app_ctx):
    token_a = _register_and_login(client, "tutor_owner@example.com")
    token_b = _register_and_login(client, "tutor_attacker@example.com")

    session_id = _create_complete_session(app_ctx, "tutor_owner@example.com")

    resp = client.post(
        "/api/tutor/chat",
        json={"message": "Tell me about this material", "session_id": session_id},
        headers=_auth_headers(token_b),
    )
    assert resp.status_code == 403
    data = resp.get_json()
    assert data["success"] is False
    # Must not reveal whether the session exists or belongs to another user
    assert "key" not in data.get("error", "").lower()
    assert "stack" not in data.get("error", "").lower()


# ---------------------------------------------------------------------------
# 8. Session with no extracted text (missing study material)
# ---------------------------------------------------------------------------

def test_tutor_chat_missing_study_material(client, app_ctx):
    """Session exists and is complete but has no extracted_texts rows."""
    token = _register_and_login(client, "tutor_nostudy@example.com")

    from db import get_db
    db = get_db()
    user = db.execute("SELECT id FROM users WHERE email = ?", ("tutor_nostudy@example.com",)).fetchone()
    session_id = str(uuid.uuid4())
    db.execute(
        """INSERT INTO analysis_sessions
           (id, student_id, status, created_at, full_report_json, revision_plan_json)
           VALUES (?, ?, 'complete', ?, ?, ?)""",
        (session_id, user["id"], dt.datetime.utcnow().isoformat(),
         json.dumps({"knowledge_gaps": [], "coverage_summary": {}}),
         json.dumps({"tasks": [], "total_minutes": 0})),
    )
    db.commit()

    # Even without extracted text, the tutor should still attempt (empty context)
    # The call will reach the AI layer — mock it to return a response
    mock_cls, _ = _mock_groq_response("I don't have much material to work with.")
    with patch("tutor.openai.OpenAI", mock_cls):
        resp = client.post(
            "/api/tutor/chat",
            json={"message": "What should I study?", "session_id": session_id},
            headers=_auth_headers(token),
        )
    # Should succeed (tutor handles empty text gracefully)
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True


# ---------------------------------------------------------------------------
# 9. AI provider failure
# ---------------------------------------------------------------------------

def test_tutor_chat_ai_failure(client, app_ctx):
    token = _register_and_login(client, "tutor_aifail@example.com")
    session_id = _create_complete_session(app_ctx, "tutor_aifail@example.com")

    import openai as _openai
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = _openai.APIError(
        "Service unavailable", request=MagicMock(), body=None
    )
    mock_cls = MagicMock(return_value=mock_client)

    with patch("tutor.openai.OpenAI", mock_cls):
        resp = client.post(
            "/api/tutor/chat",
            json={"message": "Hello", "session_id": session_id},
            headers=_auth_headers(token),
        )

    assert resp.status_code == 500
    data = resp.get_json()
    assert data["success"] is False
    # Must not expose API keys or secrets
    assert "gsk_" not in data.get("error", "")
    assert "GROQ_API_KEY" not in data.get("error", "")


# ---------------------------------------------------------------------------
# 10. AI timeout
# ---------------------------------------------------------------------------

def test_tutor_chat_ai_timeout(client, app_ctx):
    token = _register_and_login(client, "tutor_timeout@example.com")
    session_id = _create_complete_session(app_ctx, "tutor_timeout@example.com")

    import openai as _openai
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = _openai.APITimeoutError(
        request=MagicMock()
    )
    mock_cls = MagicMock(return_value=mock_client)

    with patch("tutor.openai.OpenAI", mock_cls):
        resp = client.post(
            "/api/tutor/chat",
            json={"message": "Hello", "session_id": session_id},
            headers=_auth_headers(token),
        )

    assert resp.status_code == 408
    assert resp.get_json()["success"] is False


# ---------------------------------------------------------------------------
# 11. Response does not expose secrets
# ---------------------------------------------------------------------------

def test_tutor_response_does_not_expose_secrets(client, app_ctx):
    token = _register_and_login(client, "tutor_secrets@example.com")
    session_id = _create_complete_session(app_ctx, "tutor_secrets@example.com")

    mock_cls, _ = _mock_groq_response("Here is your answer.")
    with patch("tutor.openai.OpenAI", mock_cls):
        resp = client.post(
            "/api/tutor/chat",
            json={"message": "What is my API key?", "session_id": session_id},
            headers=_auth_headers(token),
        )

    assert resp.status_code == 200
    raw = resp.get_data(as_text=True)
    assert "GROQ_API_KEY" not in raw
    assert "JWT_SECRET" not in raw
    assert "gsk_" not in raw  # Groq key prefix


# ---------------------------------------------------------------------------
# 12. Existing authentication still works
# ---------------------------------------------------------------------------

def test_existing_auth_register_and_login(client, app_ctx):
    resp = client.post(
        "/auth/register",
        json={"email": "auth_check@example.com", "password": "Password123!"},
    )
    assert resp.status_code == 201

    resp2 = client.post(
        "/auth/login",
        json={"email": "auth_check@example.com", "password": "Password123!"},
    )
    assert resp2.status_code == 200
    data = resp2.get_json()
    assert "token" in data
    assert "expires_at" in data


# ---------------------------------------------------------------------------
# 13. Existing sessions API still works
# ---------------------------------------------------------------------------

def test_existing_sessions_api_still_works(client, app_ctx):
    """GET /api/sessions must return 200 with a sessions list for an authenticated user.

    Unauthenticated access must return 401.
    The previous 503 workaround is no longer needed — the background-thread
    approach that caused it has been removed.
    """
    # Unauthenticated request must be rejected
    resp_unauth = client.get("/api/sessions")
    assert resp_unauth.status_code == 401, "Unauthenticated access must return 401"

    token = _register_and_login(client, "sessions_check@example.com")

    resp = client.get(
        "/api/sessions",
        headers=_auth_headers(token),
    )
    assert resp.status_code == 200, (
        f"Expected 200 from GET /api/sessions, got {resp.status_code}: {resp.get_data(as_text=True)}"
    )
    data = resp.get_json()
    assert "sessions" in data, f"Response must contain 'sessions' key, got: {data}"
    assert isinstance(data["sessions"], list), "sessions must be a list"
    # New user has no sessions yet — empty list is correct
    assert data["sessions"] == [], f"New user should have empty sessions list, got: {data['sessions']}"


# ===========================================================================
# Task 16.3 — Upload validation
# ===========================================================================

def _valid_pdf_bytes(size_bytes=None):
    """Return bytes that start with %PDF magic, optionally padded to size_bytes."""
    header = b"%PDF-1.4 minimal\n"
    if size_bytes and size_bytes > len(header):
        header = header + b"\x00" * (size_bytes - len(header))
    return header


def _make_file_upload(client, token, study_material_bytes=None, syllabus_bytes=None,
                      study_material_name="study.pdf", syllabus_name="syllabus.pdf",
                      content_type="application/pdf"):
    """Send a POST /api/analyze with the given bytes as multipart files."""
    data = {}
    if study_material_bytes is not None:
        from io import BytesIO
        data["study_material"] = (BytesIO(study_material_bytes), study_material_name, content_type)
    if syllabus_bytes is not None:
        from io import BytesIO
        data["syllabus"] = (BytesIO(syllabus_bytes), syllabus_name, content_type)
    return client.post(
        "/api/analyze",
        data=data,
        content_type="multipart/form-data",
        headers={"Authorization": f"Bearer {token}"},
    )


def test_upload_missing_study_material_returns_400(client, app_ctx):
    token = _register_and_login(client, "upload_nostudy@example.com")
    resp = _make_file_upload(client, token,
                             study_material_bytes=None,
                             syllabus_bytes=_valid_pdf_bytes())
    assert resp.status_code == 400
    assert "study_material" in resp.get_data(as_text=True)


def test_upload_missing_syllabus_returns_400(client, app_ctx):
    token = _register_and_login(client, "upload_nosyllabus@example.com")
    resp = _make_file_upload(client, token,
                             study_material_bytes=_valid_pdf_bytes(),
                             syllabus_bytes=None)
    assert resp.status_code == 400
    assert "syllabus" in resp.get_data(as_text=True)


def test_upload_invalid_pdf_magic_bytes_returns_415(client, app_ctx):
    token = _register_and_login(client, "upload_badpdf@example.com")
    bad_bytes = b"NOT A PDF AT ALL - this is just text"
    resp = _make_file_upload(client, token,
                             study_material_bytes=bad_bytes,
                             syllabus_bytes=bad_bytes)
    assert resp.status_code == 415


def test_upload_exactly_20mib_is_accepted_by_size_validation(client, app_ctx):
    """Exactly 20 MiB must not be rejected by the size check.

    The route will fail downstream (extraction/analysis), but the important
    assertion is that it passes validation (no 413).
    """
    from unittest.mock import patch
    token = _register_and_login(client, "upload_20mib@example.com")
    twenty_mib = _valid_pdf_bytes(size_bytes=20 * 1024 * 1024)

    # Mock everything downstream so we only test the size validation boundary
    from extraction import ExtractionResult
    mock_result = ExtractionResult(text="x" * 200, char_count=200, warnings=[])
    with patch("app.extract", return_value=mock_result), \
         patch("app.save_upload", return_value="/tmp/fake.pdf"), \
         patch("app.run_analysis") as mock_analysis:
        from analyzer import AnalysisResult
        mock_analysis.return_value = AnalysisResult(
            topics=[], readiness_score=0,
            coverage_summary={"total": 0, "covered": 0, "partially_covered": 0, "missing": 0},
            knowledge_gaps=[], warnings=[], revision_plan={"tasks": [], "total_minutes": 0},
        )
        resp = _make_file_upload(client, token,
                                 study_material_bytes=twenty_mib,
                                 syllabus_bytes=twenty_mib)
    # Must not be 413 (size rejection)
    assert resp.status_code != 413, f"20 MiB was incorrectly rejected with 413"


def test_upload_20mib_plus_1_byte_returns_413(client, app_ctx):
    token = _register_and_login(client, "upload_toolarge@example.com")
    over_limit = _valid_pdf_bytes(size_bytes=20 * 1024 * 1024 + 1)
    resp = _make_file_upload(client, token,
                             study_material_bytes=over_limit,
                             syllabus_bytes=_valid_pdf_bytes())
    assert resp.status_code == 413


def test_upload_unauthenticated_returns_401(client, app_ctx):
    from io import BytesIO
    resp = client.post(
        "/api/analyze",
        data={
            "study_material": (BytesIO(_valid_pdf_bytes()), "study.pdf", "application/pdf"),
            "syllabus": (BytesIO(_valid_pdf_bytes()), "syllabus.pdf", "application/pdf"),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 401


# ===========================================================================
# Task 16.6 — Session history
# ===========================================================================

def test_history_empty_list_for_new_user(client, app_ctx):
    token = _register_and_login(client, "hist_empty@example.com")
    resp = client.get("/api/sessions", headers=_auth_headers(token))
    assert resp.status_code == 200
    assert resp.get_json()["sessions"] == []


def test_history_sessions_returned_descending_order(client, app_ctx):
    """Sessions must be ordered newest-first (created_at DESC)."""
    from db import get_db
    import uuid
    token = _register_and_login(client, "hist_order@example.com")
    db = get_db()
    user = db.execute("SELECT id FROM users WHERE email = ?", ("hist_order@example.com",)).fetchone()

    # Insert 3 sessions with explicit timestamps
    sessions_data = [
        ("2024-01-01 10:00:00",),
        ("2024-01-03 10:00:00",),  # newest
        ("2024-01-02 10:00:00",),
    ]
    session_ids = []
    for (ts,) in sessions_data:
        sid = str(uuid.uuid4())
        session_ids.append(sid)
        db.execute(
            "INSERT INTO analysis_sessions (id, student_id, status, created_at) VALUES (?, ?, 'complete', ?)",
            (sid, user["id"], ts),
        )
    db.commit()

    resp = client.get("/api/sessions", headers=_auth_headers(token))
    assert resp.status_code == 200
    returned = resp.get_json()["sessions"]
    assert len(returned) == 3
    dates = [s["created_at"] for s in returned]
    assert dates == sorted(dates, reverse=True)


def test_history_capped_at_100(client, app_ctx):
    from db import get_db
    import uuid
    token = _register_and_login(client, "hist_cap@example.com")
    db = get_db()
    user = db.execute("SELECT id FROM users WHERE email = ?", ("hist_cap@example.com",)).fetchone()
    for i in range(105):
        db.execute(
            "INSERT INTO analysis_sessions (id, student_id, status, created_at) VALUES (?, ?, 'complete', ?)",
            (str(uuid.uuid4()), user["id"], f"2024-01-{(i % 28) + 1:02d} {(i % 24):02d}:00:00"),
        )
    db.commit()
    resp = client.get("/api/sessions", headers=_auth_headers(token))
    assert resp.status_code == 200
    assert len(resp.get_json()["sessions"]) == 100


def test_history_cross_student_access_returns_403(client, app_ctx):
    from db import get_db
    import uuid
    token_a = _register_and_login(client, "hist_a@example.com")
    token_b = _register_and_login(client, "hist_b@example.com")
    db = get_db()
    user_a = db.execute("SELECT id FROM users WHERE email = ?", ("hist_a@example.com",)).fetchone()
    sid = str(uuid.uuid4())
    db.execute(
        "INSERT INTO analysis_sessions (id, student_id, status, created_at) VALUES (?, ?, 'complete', ?)",
        (sid, user_a["id"], dt.datetime.utcnow().isoformat()),
    )
    db.commit()
    resp = client.get(f"/api/sessions/{sid}", headers=_auth_headers(token_b))
    assert resp.status_code == 403
    assert resp.get_json() == {"error": "Not found"}


def test_history_unknown_session_returns_404(client, app_ctx):
    token = _register_and_login(client, "hist_404@example.com")
    resp = client.get(f"/api/sessions/{uuid.uuid4()}", headers=_auth_headers(token))
    assert resp.status_code == 404
