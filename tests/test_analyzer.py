"""
test_analyzer.py — Unit tests for the AI analyzer (Task 16.5).
All Groq/OpenAI API calls are mocked — no real API key needed.
"""
import sys
import pathlib
import json

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from unittest.mock import MagicMock, patch
import pytest
import openai as _openai

from analyzer import run_analysis, PipelineError, PipelineTimeoutError


# ---------------------------------------------------------------------------
# Test data — valid responses
# ---------------------------------------------------------------------------

_VALID_ANALYSIS_JSON = json.dumps({
    "topics": [
        {"title": "OOP", "importance": "high", "coverage_status": "covered",
         "reasoning": "Fully covered.", "key_gaps": []},
        {"title": "Inheritance", "importance": "medium", "coverage_status": "covered",
         "reasoning": "Well covered.", "key_gaps": []},
        {"title": "Polymorphism", "importance": "low", "coverage_status": "missing",
         "reasoning": "Not found.", "key_gaps": ["method overriding"]},
    ],
    "readiness_score": 67,
    "coverage_summary": {"total": 3, "covered": 2, "partially_covered": 0, "missing": 1},
    "knowledge_gaps": [
        {"topic_title": "Polymorphism", "importance": "low",
         "coverage_status": "missing", "explanation": "Not found in material.",
         "priority_tier": 3}
    ],
})

_VALID_REVISION_JSON = json.dumps({
    "tasks": [
        {"title": "Study Polymorphism", "description": "Review method overriding.",
         "duration_minutes": 15, "gap_ref": "Polymorphism"}
    ],
    "total_minutes": 15,
    "maintenance_task": None,
})


def _make_mock_openai(responses):
    """Return (mock_cls, mock_client) where create() yields each response string in order."""
    side_effects = []
    for text in responses:
        choice = MagicMock()
        choice.message.content = text
        resp = MagicMock()
        resp.choices = [choice]
        side_effects.append(resp)
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = side_effects
    mock_cls = MagicMock(return_value=mock_client)
    return mock_cls, mock_client


# ---------------------------------------------------------------------------
# 16.5-a: Two AI calls made in sequence
# ---------------------------------------------------------------------------

def test_run_analysis_makes_two_calls_in_sequence():
    mock_cls, mock_client = _make_mock_openai([_VALID_ANALYSIS_JSON, _VALID_REVISION_JSON])
    with patch("analyzer.openai.OpenAI", mock_cls):
        run_analysis("Syllabus text.", "Study material.")
    assert mock_client.chat.completions.create.call_count == 2


# ---------------------------------------------------------------------------
# 16.5-b: Valid responses produce correct AnalysisResult
# ---------------------------------------------------------------------------

def test_run_analysis_valid_responses_produce_result():
    mock_cls, _ = _make_mock_openai([_VALID_ANALYSIS_JSON, _VALID_REVISION_JSON])
    with patch("analyzer.openai.OpenAI", mock_cls):
        result = run_analysis("Syllabus text.", "Study material.")
    assert result.readiness_score == 67
    assert len(result.topics) == 3
    assert result.coverage_summary["total"] == 3
    assert len(result.knowledge_gaps) == 1
    assert result.revision_plan["total_minutes"] == 15


# ---------------------------------------------------------------------------
# 16.5-c: APITimeoutError on Call 1 → PipelineTimeoutError
# ---------------------------------------------------------------------------

def test_run_analysis_timeout_raises_pipeline_timeout_error():
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = _openai.APITimeoutError(
        request=MagicMock()
    )
    mock_cls = MagicMock(return_value=mock_client)
    with patch("analyzer.openai.OpenAI", mock_cls):
        with pytest.raises(PipelineTimeoutError):
            run_analysis("Syllabus.", "Material.")


# ---------------------------------------------------------------------------
# 16.5-d: Invalid JSON from AI → PipelineError
# ---------------------------------------------------------------------------

def test_run_analysis_invalid_json_raises_pipeline_error():
    mock_cls, _ = _make_mock_openai(["not-valid-json{{{{", _VALID_REVISION_JSON])
    with patch("analyzer.openai.OpenAI", mock_cls):
        with pytest.raises(PipelineError) as exc_info:
            run_analysis("Syllabus.", "Material.")
    msg = exc_info.value.message.lower()
    assert "json" in msg or "invalid" in msg


# ---------------------------------------------------------------------------
# 16.5-e: Sparse syllabus (< 3 topics) → warning in result
# ---------------------------------------------------------------------------

def test_run_analysis_sparse_syllabus_produces_warning():
    sparse_analysis = json.dumps({
        "topics": [
            {"title": "OOP", "importance": "high", "coverage_status": "covered",
             "reasoning": "Covered.", "key_gaps": []},
            {"title": "Inheritance", "importance": "medium", "coverage_status": "covered",
             "reasoning": "Covered.", "key_gaps": []},
        ],
        "readiness_score": 100,
        "coverage_summary": {"total": 2, "covered": 2, "partially_covered": 0, "missing": 0},
        "knowledge_gaps": [],
    })
    sparse_revision = json.dumps({
        "tasks": [], "total_minutes": 0, "maintenance_task": None
    })
    mock_cls, _ = _make_mock_openai([sparse_analysis, sparse_revision])
    with patch("analyzer.openai.OpenAI", mock_cls):
        result = run_analysis("Sparse syllabus.", "Material.")
    assert len(result.topics) == 2
    assert any(
        "3" in w or "sparse" in w.lower() or "topic" in w.lower()
        for w in result.warnings
    )
