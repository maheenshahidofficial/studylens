from __future__ import annotations

import dataclasses
import json
import logging
import os
import time
from typing import Any, Dict, List, Literal, Optional

import openai
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)


class TopicModel(BaseModel):
    title: str
    importance: Literal["high", "medium", "low"]
    coverage_status: Literal["covered", "partially_covered", "missing"]
    reasoning: str
    key_gaps: List[str]


class KnowledgeGapModel(BaseModel):
    topic_title: str
    importance: Literal["high", "medium", "low"]
    coverage_status: Literal["partially_covered", "missing"]
    explanation: str
    priority_tier: int = Field(..., ge=1, le=6)


class CoverageSummaryModel(BaseModel):
    total: int = Field(..., ge=0)
    covered: int = Field(..., ge=0)
    partially_covered: int = Field(..., ge=0)
    missing: int = Field(..., ge=0)


class AnalysisResponseModel(BaseModel):
    topics: List[TopicModel] = Field(..., min_length=1, max_length=200)
    readiness_score: int = Field(..., ge=0, le=100)
    coverage_summary: CoverageSummaryModel
    knowledge_gaps: List[KnowledgeGapModel]


class RevisionTaskModel(BaseModel):
    title: str
    description: str
    duration_minutes: int = Field(..., ge=0)
    gap_ref: Optional[str] = None


class RevisionPlanModel(BaseModel):
    tasks: List[RevisionTaskModel]
    total_minutes: int = Field(..., ge=0)
    maintenance_task: Optional[RevisionTaskModel] = None


# ---------------------------------------------------------------------------
# Task 7.2 — Pure computation helpers
# ---------------------------------------------------------------------------

def compute_readiness_score(covered: int, total: int) -> int:
    """Compute the exam readiness score as a percentage.

    Args:
        covered: Number of topics with coverage_status == "covered".
        total:   Total number of topics in the syllabus.

    Returns:
        Integer score 0–100, rounded to the nearest whole number.
        Returns 0 if total is 0 to avoid division by zero.
    """
    if total == 0:
        return 0
    return round((covered / total) * 100)


# Mapping from (coverage_status, importance) pair to six-tier priority integer.
# Lower integer = higher priority (1 is most urgent).
_GAP_PRIORITY: dict[tuple[str, str], int] = {
    ("missing",           "high"):   1,
    ("missing",           "medium"): 2,
    ("missing",           "low"):    3,
    ("partially_covered", "high"):   4,
    ("partially_covered", "medium"): 5,
    ("partially_covered", "low"):    6,
}


def _gap_tier(gap: dict) -> int:
    """Return the priority tier (1–6) for a single knowledge gap dict."""
    return _GAP_PRIORITY.get(
        (gap.get("coverage_status", "missing"), gap.get("importance", "low")),
        6,  # unknown combinations fall to lowest priority
    )


def build_coverage_summary(statuses: list) -> dict:
    """Count topics by coverage status.

    Args:
        statuses: List of coverage status strings, each one of
                  "covered", "partially_covered", or "missing".

    Returns:
        Dict with keys: total, covered, partially_covered, missing.
    """
    covered = statuses.count("covered")
    partially_covered = statuses.count("partially_covered")
    missing = statuses.count("missing")
    return {
        "total": len(statuses),
        "covered": covered,
        "partially_covered": partially_covered,
        "missing": missing,
    }


def rank_knowledge_gaps(gaps: list) -> list:
    """Sort a list of knowledge gap dicts by six-tier priority (stable sort).

    Tier 1 (missing + high importance) comes first;
    Tier 6 (partially_covered + low importance) comes last.
    Gaps at the same tier preserve their original relative order.

    Args:
        gaps: List of dicts, each containing at minimum
              "coverage_status" and "importance" keys.

    Returns:
        New list sorted by ascending priority tier.
    """
    return sorted(gaps, key=_gap_tier)


# Duration in minutes assigned to a revision task based on topic importance.
_DURATION_BY_IMPORTANCE: dict[str, int] = {
    "high":   60,
    "medium": 30,
    "low":    15,
}

_MAINTENANCE_DURATION = 30


def build_revision_plan(gaps: list) -> dict:
    """Build a revision plan from a ranked list of knowledge gaps.

    Creates one revision task per gap using the importance-based duration
    mapping.  When there are no gaps, produces a single maintenance task
    recommending the student review all covered topics.

    Args:
        gaps: Ordered list of knowledge gap dicts.  Each dict must contain
              at minimum "topic_title" (str) and "importance" (str) keys.

    Returns:
        Dict with keys:
            tasks        — list of revision task dicts
            total_minutes — sum of all task durations
    """
    if not gaps:
        maintenance = {
            "title": "Review all covered topics",
            "description": (
                "Your study material covers all syllabus topics. "
                "Review the covered material before your exam to consolidate your knowledge."
            ),
            "duration_minutes": _MAINTENANCE_DURATION,
            "gap_ref": None,
            "is_maintenance": True,
        }
        return {
            "tasks": [maintenance],
            "total_minutes": _MAINTENANCE_DURATION,
        }

    tasks = []
    for gap in gaps:
        importance = gap.get("importance", "low")
        duration = _DURATION_BY_IMPORTANCE.get(importance, 15)
        task = {
            "title": f"Study: {gap.get('topic_title', 'Unknown topic')}",
            "description": gap.get("explanation", ""),
            "duration_minutes": duration,
            "gap_ref": gap.get("topic_title", ""),
            "is_maintenance": False,
        }
        tasks.append(task)

    total_minutes = sum(t["duration_minutes"] for t in tasks)
    return {
        "tasks": tasks,
        "total_minutes": total_minutes,
    }


# ---------------------------------------------------------------------------
# Task 7.3 — Pipeline exceptions, AnalysisResult, and run_analysis
# ---------------------------------------------------------------------------

class PipelineError(Exception):
    """Raised when an AI pipeline stage fails (parse error, API error, etc.)."""
    def __init__(self, stage: str, message: str):
        super().__init__(f"Pipeline error at stage '{stage}': {message}")
        self.stage = stage
        self.message = message
        self.status_code = 500


class PipelineTimeoutError(Exception):
    """Raised when an AI pipeline stage or total budget exceeds the time limit."""
    def __init__(self, stage: str):
        super().__init__(f"Pipeline timed out at stage '{stage}'")
        self.stage = stage
        self.status_code = 504


@dataclasses.dataclass
class AnalysisResult:
    """Combined output of the two-call AI analysis pipeline."""
    # From Call 1
    topics: list
    readiness_score: int
    coverage_summary: dict
    knowledge_gaps: list
    warnings: List[str]
    # From Call 2
    revision_plan: dict


_TOTAL_PIPELINE_BUDGET = 50.0   # seconds (reduced for Vercel 60s limit)
_PER_CALL_TIMEOUT = 25          # seconds (reduced for Vercel 60s limit)

_GROQ_BASE_URL = "https://api.groq.com/openai/v1"
_DEFAULT_MODEL = "openai/gpt-oss-120b"


def _call_openai(messages: list, stage: str, pipeline_start: float) -> str:
    """Make a single OpenAI Chat Completions call with timeout and budget checks.

    Args:
        messages:        List of message dicts for the chat API.
        stage:           Pipeline stage name for error reporting.
        pipeline_start:  time.monotonic() value at the start of the pipeline.

    Returns:
        The raw content string from the first completion choice.

    Raises:
        PipelineTimeoutError: On per-call timeout or total budget exceeded.
        PipelineError:         On API errors or empty response content.
    """
    # Check total budget before making the call
    if time.monotonic() - pipeline_start >= _TOTAL_PIPELINE_BUDGET:
        raise PipelineTimeoutError(stage)

    api_key = os.environ.get("GROQ_API_KEY")
    model = os.environ.get("GROQ_MODEL", _DEFAULT_MODEL)
    client = openai.OpenAI(
        api_key=api_key,
        base_url=_GROQ_BASE_URL,
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            timeout=_PER_CALL_TIMEOUT,
            response_format={"type": "json_object"},
        )
    except (openai.APITimeoutError, openai.APIConnectionError):
        raise PipelineTimeoutError(stage)
    except openai.AuthenticationError as exc:
        logger.error("Groq authentication error at stage '%s': check GROQ_API_KEY", stage)
        raise PipelineError(stage, "AI service authentication failed. Please check server configuration.")
    except openai.RateLimitError as exc:
        logger.error("Groq rate limit error at stage '%s'", stage)
        raise PipelineError(stage, "AI service rate limit reached. Please try again in a moment.")
    except openai.APIError as exc:
        logger.error("Groq API error at stage '%s': %s", stage, str(exc))
        raise PipelineError(stage, f"AI service error: {exc.message if hasattr(exc, 'message') else str(exc)}")

    # Check total budget after the call returns
    if time.monotonic() - pipeline_start >= _TOTAL_PIPELINE_BUDGET:
        raise PipelineTimeoutError(stage)

    content = response.choices[0].message.content if response.choices else None
    if not content:
        raise PipelineError(stage, "Empty response from AI service")
    return content


def _build_analysis_prompt(syllabus_text: str, study_material_text: str) -> list:
    """Build the Call 1 messages: system prompt + user message with both texts."""
    system_prompt = (
        "You are an expert academic analyst. Analyse the provided syllabus against "
        "the study material and return a JSON object that strictly conforms to the "
        "following schema:\n\n"
        "{\n"
        "  \"topics\": [\n"
        "    {\n"
        "      \"title\": string,\n"
        "      \"importance\": \"high\" | \"medium\" | \"low\",\n"
        "      \"coverage_status\": \"covered\" | \"partially_covered\" | \"missing\",\n"
        "      \"reasoning\": string (1-3 sentences explaining the classification),\n"
        "      \"key_gaps\": [string] (list of missing subtopics; empty if covered)\n"
        "    }\n"
        "  ],\n"
        "  \"readiness_score\": integer (0-100, percentage of covered topics),\n"
        "  \"coverage_summary\": {\n"
        "    \"total\": integer,\n"
        "    \"covered\": integer,\n"
        "    \"partially_covered\": integer,\n"
        "    \"missing\": integer\n"
        "  },\n"
        "  \"knowledge_gaps\": [\n"
        "    {\n"
        "      \"topic_title\": string,\n"
        "      \"importance\": \"high\" | \"medium\" | \"low\",\n"
        "      \"coverage_status\": \"partially_covered\" | \"missing\",\n"
        "      \"explanation\": string (max 100 words describing what is absent),\n"
        "      \"priority_tier\": integer 1-6 (1=missing+high, 2=missing+medium, "
        "3=missing+low, 4=partially_covered+high, 5=partially_covered+medium, "
        "6=partially_covered+low)\n"
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        "- Include ONLY topics from the syllabus.\n"
        "- readiness_score = round((covered_count / total_topics) * 100).\n"
        "- knowledge_gaps must contain every topic with status partially_covered or missing.\n"
        "- Return valid JSON only. No markdown, no commentary outside the JSON object."
    )
    user_message = (
        f"SYLLABUS:\n{syllabus_text}\n\n"
        f"STUDY MATERIAL:\n{study_material_text}"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]


def _build_revision_prompt(knowledge_gaps: list) -> list:
    """Build the Call 2 messages: system prompt + knowledge gaps JSON."""
    system_prompt = (
        "You are an expert study planner. Given a list of knowledge gaps, create a "
        "personalised revision plan and return a JSON object conforming to:\n\n"
        "{\n"
        "  \"tasks\": [\n"
        "    {\n"
        "      \"title\": string,\n"
        "      \"description\": string (what to study and why),\n"
        "      \"duration_minutes\": integer,\n"
        "      \"gap_ref\": string (topic_title of the gap this task addresses)\n"
        "    }\n"
        "  ],\n"
        "  \"total_minutes\": integer (sum of all duration_minutes),\n"
        "  \"maintenance_task\": null\n"
        "}\n\n"
        "Rules:\n"
        "- One task per knowledge gap, ordered by priority_tier ascending.\n"
        "- duration_minutes: 60 for high importance, 30 for medium, 15 for low.\n"
        "- total_minutes must equal the arithmetic sum of all task duration_minutes.\n"
        "- Return valid JSON only. No markdown, no commentary outside the JSON object."
    )
    user_message = (
        f"KNOWLEDGE GAPS (JSON):\n{json.dumps(knowledge_gaps, indent=2)}"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]


def run_analysis(syllabus_text: str, study_material_text: str) -> AnalysisResult:
    """Run the two-call AI analysis pipeline and return a structured result.

    Call 1 — Full analysis:
        Sends both texts to OpenAI, receives topics with coverage status,
        readiness score, coverage summary, and knowledge gaps.

    Call 2 — Revision plan:
        Sends the knowledge gaps from Call 1 to OpenAI, receives an ordered
        revision plan with per-task durations.

    Each call has a 60-second per-call timeout. The entire pipeline must
    complete within 120 seconds from the moment this function is called.

    Args:
        syllabus_text:        Extracted text from the course syllabus PDF.
        study_material_text:  Extracted text from the study material PDF.

    Returns:
        AnalysisResult combining Call 1 and Call 2 outputs.

    Raises:
        PipelineTimeoutError: If a call exceeds 60 s or the total exceeds 120 s.
        PipelineError:        If the AI returns an error, empty content, invalid
                              JSON, or a response that fails Pydantic validation.
    """
    pipeline_start = time.monotonic()
    warnings: List[str] = []

    # ------------------------------------------------------------------
    # Call 1 — Full analysis
    # ------------------------------------------------------------------
    stage_1 = "concept_extraction_and_coverage"
    messages_1 = _build_analysis_prompt(syllabus_text, study_material_text)
    raw_1 = _call_openai(messages_1, stage_1, pipeline_start)

    try:
        data_1 = json.loads(raw_1)
    except json.JSONDecodeError as exc:
        raise PipelineError(stage_1, f"Invalid JSON from AI: {exc}")

    try:
        analysis = AnalysisResponseModel.model_validate(data_1)
    except ValidationError as exc:
        raise PipelineError(stage_1, f"Response validation failed: {exc}")

    # Sparse-syllabus warning
    if len(analysis.topics) < 3:
        warnings.append(
            "The syllabus contains fewer than 3 identifiable topics. "
            "The analysis may not be meaningful."
        )

    # ------------------------------------------------------------------
    # Call 2 — Revision plan
    # ------------------------------------------------------------------
    stage_2 = "revision_plan_generation"

    # Serialize knowledge_gaps for the prompt
    gaps_for_prompt = [gap.model_dump() for gap in analysis.knowledge_gaps]

    messages_2 = _build_revision_prompt(gaps_for_prompt)
    raw_2 = _call_openai(messages_2, stage_2, pipeline_start)

    try:
        data_2 = json.loads(raw_2)
    except json.JSONDecodeError as exc:
        raise PipelineError(stage_2, f"Invalid JSON from AI: {exc}")

    try:
        revision = RevisionPlanModel.model_validate(data_2)
    except ValidationError as exc:
        raise PipelineError(stage_2, f"Response validation failed: {exc}")

    # Final budget check after both calls
    if time.monotonic() - pipeline_start >= _TOTAL_PIPELINE_BUDGET:
        raise PipelineTimeoutError(stage_2)

    return AnalysisResult(
        topics=[t.model_dump() for t in analysis.topics],
        readiness_score=analysis.readiness_score,
        coverage_summary=analysis.coverage_summary.model_dump(),
        knowledge_gaps=[g.model_dump() for g in analysis.knowledge_gaps],
        warnings=warnings,
        revision_plan=revision.model_dump(),
    )
