"""
test_properties.py — Property-based and unit tests for StudyLens AI.
Task 15: Properties 1–6.
"""
import sys
import pathlib
import uuid
import datetime as dt

import pytest
from hypothesis import given, settings, strategies as st

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from analyzer import (
    build_coverage_summary,
    build_revision_plan,
    compute_readiness_score,
    rank_knowledge_gaps,
    _GAP_PRIORITY,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_COVERAGE_STATUSES = ["covered", "partially_covered", "missing"]
_GAP_STATUSES = ["partially_covered", "missing"]
_IMPORTANCE_LEVELS = ["high", "medium", "low"]


@st.composite
def gap_strategy(draw):
    """A valid knowledge-gap dict with coverage_status and importance."""
    return {
        "coverage_status": draw(st.sampled_from(_GAP_STATUSES)),
        "importance":      draw(st.sampled_from(_IMPORTANCE_LEVELS)),
        "topic_title":     draw(st.text(min_size=1, max_size=20,
                                        alphabet="abcdefghijklmnopqrstuvwxyz ")),
        "explanation":     "test",
    }


def _tier(gap):
    return _GAP_PRIORITY.get(
        (gap.get("coverage_status", "missing"), gap.get("importance", "low")), 6
    )


# ---------------------------------------------------------------------------
# 15.1 — Readiness Score formula (Property 1)
# Validates: Requirements 7.2
# ---------------------------------------------------------------------------

@given(
    total=st.integers(min_value=1, max_value=200),
    covered=st.integers(min_value=0, max_value=200),
)
@settings(max_examples=100)
def test_readiness_score_formula(total, covered):
    covered = min(covered, total)
    assert compute_readiness_score(covered, total) == round((covered / total) * 100)


# ---------------------------------------------------------------------------
# 15.2 — Coverage counts sum to total (Property 2)
# Validates: Requirements 5.5
# ---------------------------------------------------------------------------

@given(
    st.lists(st.sampled_from(_COVERAGE_STATUSES), min_size=1, max_size=200)
)
@settings(max_examples=100)
def test_coverage_counts_sum_to_total(statuses):
    s = build_coverage_summary(statuses)
    assert s["covered"] + s["partially_covered"] + s["missing"] == s["total"]
    assert s["total"] == len(statuses)


# ---------------------------------------------------------------------------
# 15.3 — Knowledge Gap six-tier priority order (Property 3)
# Validates: Requirements 6.2, 8.2
# ---------------------------------------------------------------------------

@given(st.lists(gap_strategy(), min_size=1, max_size=50))
@settings(max_examples=100)
def test_knowledge_gap_ranking_order(gaps):
    ranked = rank_knowledge_gaps(gaps)
    for i in range(len(ranked) - 1):
        assert _tier(ranked[i]) <= _tier(ranked[i + 1])


# ---------------------------------------------------------------------------
# 15.4 — Revision plan total == sum of task durations (Property 4)
# Validates: Requirements 8.5
# ---------------------------------------------------------------------------

@given(st.lists(gap_strategy(), min_size=0, max_size=50))
@settings(max_examples=100)
def test_revision_plan_total_equals_sum(gaps):
    plan = build_revision_plan(gaps)
    assert plan["total_minutes"] == sum(t["duration_minutes"] for t in plan["tasks"])


# ---------------------------------------------------------------------------
# 15.5 — Passwords never stored in plaintext (Property 5)
# Validates: Requirements 1.5
# ---------------------------------------------------------------------------

def test_passwords_never_stored_in_plaintext(client, app_ctx):
    plaintext = "SecurePass123!"
    r = client.post(
        "/auth/register",
        json={"email": "bcrypt_test@example.com", "password": plaintext},
        content_type="application/json",
    )
    assert r.status_code == 201, r.get_json()

    from db import get_db
    row = get_db().execute(
        "SELECT password_hash FROM users WHERE email = ?",
        ("bcrypt_test@example.com",),
    ).fetchone()

    assert row is not None
    h = row["password_hash"]
    assert h != plaintext, "hash must not equal plaintext"
    assert h.startswith("$2b$"), f"expected bcrypt hash, got: {h[:12]}"


# ---------------------------------------------------------------------------
# 15.6 — Cross-student session access returns 403 (Property 6)
# Validates: Requirements 9.4
# ---------------------------------------------------------------------------

def _register_and_login(client, email, pw="Password123!"):
    client.post("/auth/register", json={"email": email, "password": pw})
    r = client.post("/auth/login", json={"email": email, "password": pw})
    return r.get_json()["token"]


def test_cross_student_session_access_returns_403(client, app_ctx):
    token_a = _register_and_login(client, "user_a_prop@example.com")
    token_b = _register_and_login(client, "user_b_prop@example.com")

    from db import get_db
    db = get_db()
    user_a = db.execute(
        "SELECT id FROM users WHERE email = ?", ("user_a_prop@example.com",)
    ).fetchone()
    session_id = str(uuid.uuid4())
    db.execute(
        """INSERT INTO analysis_sessions (id, student_id, status, created_at)
           VALUES (?, ?, 'complete', ?)""",
        (session_id, user_a["id"], dt.datetime.utcnow().isoformat()),
    )
    db.commit()

    resp = client.get(
        f"/api/sessions/{session_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp.status_code == 403
    assert resp.get_json() == {"error": "Not found"}
