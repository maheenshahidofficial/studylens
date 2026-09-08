"""
tutor.py — Context-aware AI Study Tutor for StudyLens AI

Provides a conversational AI tutor grounded in the student's uploaded
study material, syllabus, analysis results, and revision plan.

Public API:
    build_tutor_context(session_id, db) -> TutorContext
    get_tutor_response(session_id, user_message, db) -> dict
"""
from __future__ import annotations

import dataclasses
import json
import logging
import os
from typing import List, Optional

import openai

from db import count_tutor_messages, get_tutor_messages, save_tutor_message

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Groq configuration — identical to analyzer.py
# ---------------------------------------------------------------------------

_GROQ_BASE_URL = "https://api.groq.com/openai/v1"
_DEFAULT_MODEL = "openai/gpt-oss-120b"

# Context window budget (characters, not tokens — conservative estimate)
_MAX_STUDY_MATERIAL_CHARS = 40_000
_MAX_SYLLABUS_CHARS = 10_000
_CONVERSATION_HISTORY_LIMIT = 10
_MESSAGE_LIMIT_PER_SESSION = 100
_TUTOR_TIMEOUT = 60  # seconds

# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class TutorError(Exception):
    """Raised when the AI tutor call fails for a non-timeout reason."""

    def __init__(self, message: str = "AI tutor request failed"):
        super().__init__(message)
        self.message = message
        self.status_code = 500


class TutorTimeoutError(Exception):
    """Raised when the AI tutor does not respond within the timeout budget."""

    def __init__(self, message: str = "AI tutor request timed out"):
        super().__init__(message)
        self.message = message
        self.status_code = 408


class TutorMessageLimitError(Exception):
    """Raised when a session has reached the 100-message limit."""

    def __init__(self, message: str = "Message limit reached for this session"):
        super().__init__(message)
        self.message = message
        self.status_code = 429


class TutorContextError(Exception):
    """Raised when session context cannot be loaded for the tutor."""

    def __init__(self, message: str = "Could not load session context for tutor"):
        super().__init__(message)
        self.message = message
        self.status_code = 500


# ---------------------------------------------------------------------------
# TutorContext dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class TutorContext:
    """All context needed to run a tutor conversation for one analysis session."""

    syllabus_text: str
    study_material_text: str
    coverage_summary: dict          # {total, covered, partially_covered, missing}
    knowledge_gaps: list            # ranked list of gap dicts
    revision_plan: dict             # {tasks: [...], total_minutes: N}
    conversation_history: List[dict]  # [{"role": "user"|"assistant", "content": "..."}]


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------


def build_tutor_context(session_id: str, db) -> TutorContext:
    """Load all context required for the AI tutor from the database.

    Loads the session record, extracted texts, analysis results, revision
    plan, and the most recent conversation turns.  Truncates large text
    fields to stay within the model's context window budget.

    Args:
        session_id: UUID of a complete analysis session.
        db:         sqlite3 connection (with row_factory = sqlite3.Row).

    Returns:
        A TutorContext populated from the database.

    Raises:
        TutorContextError: If the session does not exist or context cannot
                           be assembled.
    """
    # ------------------------------------------------------------------
    # 1. Load and validate the session
    # ------------------------------------------------------------------
    session_row = db.execute(
        "SELECT id, student_id, status, full_report_json, revision_plan_json "
        "FROM analysis_sessions WHERE id = ?",
        (session_id,),
    ).fetchone()

    if session_row is None:
        raise TutorContextError("Session not found")
    if session_row["status"] != "complete":
        raise TutorContextError("Session analysis is not complete")

    # ------------------------------------------------------------------
    # 2. Parse full_report_json and revision_plan_json
    # ------------------------------------------------------------------
    full_report = {}
    revision_plan = {}

    if session_row["full_report_json"]:
        try:
            full_report = json.loads(session_row["full_report_json"])
        except (json.JSONDecodeError, TypeError):
            logger.warning("Could not parse full_report_json for session %s", session_id)

    if session_row["revision_plan_json"]:
        try:
            revision_plan = json.loads(session_row["revision_plan_json"])
        except (json.JSONDecodeError, TypeError):
            logger.warning("Could not parse revision_plan_json for session %s", session_id)

    coverage_summary = full_report.get("coverage_summary", {})
    knowledge_gaps = full_report.get("knowledge_gaps", [])

    # ------------------------------------------------------------------
    # 3. Load extracted texts (study material + syllabus)
    # ------------------------------------------------------------------
    text_rows = db.execute(
        "SELECT doc_type, content FROM extracted_texts WHERE session_id = ?",
        (session_id,),
    ).fetchall()

    study_material_text = ""
    syllabus_text = ""

    for row in text_rows:
        if row["doc_type"] == "study_material":
            study_material_text = row["content"] or ""
        elif row["doc_type"] == "syllabus":
            syllabus_text = row["content"] or ""

    # ------------------------------------------------------------------
    # 4. Truncate to context window budget
    # ------------------------------------------------------------------
    if len(study_material_text) > _MAX_STUDY_MATERIAL_CHARS:
        study_material_text = study_material_text[:_MAX_STUDY_MATERIAL_CHARS]
        logger.info(
            "Study material truncated to %d chars for session %s",
            _MAX_STUDY_MATERIAL_CHARS,
            session_id,
        )

    if len(syllabus_text) > _MAX_SYLLABUS_CHARS:
        syllabus_text = syllabus_text[:_MAX_SYLLABUS_CHARS]
        logger.info(
            "Syllabus truncated to %d chars for session %s",
            _MAX_SYLLABUS_CHARS,
            session_id,
        )

    # ------------------------------------------------------------------
    # 5. Load recent conversation history (chronological ASC order)
    # ------------------------------------------------------------------
    history_rows = get_tutor_messages(session_id, limit=_CONVERSATION_HISTORY_LIMIT)
    conversation_history = [
        {"role": row["role"], "content": row["content"]}
        for row in history_rows
    ]

    return TutorContext(
        syllabus_text=syllabus_text,
        study_material_text=study_material_text,
        coverage_summary=coverage_summary,
        knowledge_gaps=knowledge_gaps,
        revision_plan=revision_plan,
        conversation_history=conversation_history,
    )


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------


def _build_system_prompt(ctx: TutorContext) -> str:
    """Build the system prompt that grounds the tutor in the student's material."""

    # Summarise top knowledge gaps (max 5) for the prompt
    top_gaps = ctx.knowledge_gaps[:5]
    gaps_text = ""
    if top_gaps:
        gap_lines = []
        for gap in top_gaps:
            title = gap.get("topic_title", "Unknown topic")
            status = gap.get("coverage_status", "missing")
            importance = gap.get("importance", "medium")
            explanation = gap.get("explanation", "")
            gap_lines.append(
                f"  - {title} ({status}, {importance} importance): {explanation}"
            )
        gaps_text = "TOP KNOWLEDGE GAPS:\n" + "\n".join(gap_lines)

    # Summarise revision plan
    revision_text = ""
    if ctx.revision_plan and ctx.revision_plan.get("tasks"):
        total = ctx.revision_plan.get("total_minutes", 0)
        task_count = len(ctx.revision_plan["tasks"])
        next_task = ctx.revision_plan["tasks"][0] if ctx.revision_plan["tasks"] else None
        revision_text = (
            f"REVISION PLAN SUMMARY:\n"
            f"  Total tasks: {task_count}, Total estimated time: {total} minutes\n"
        )
        if next_task:
            revision_text += f"  Next priority task: {next_task.get('title', '')}"

    # Coverage summary
    cs = ctx.coverage_summary
    coverage_text = (
        f"COVERAGE SUMMARY: "
        f"{cs.get('covered', 0)} covered, "
        f"{cs.get('partially_covered', 0)} partially covered, "
        f"{cs.get('missing', 0)} missing "
        f"(out of {cs.get('total', 0)} total topics)"
    ) if cs else ""

    return (
        "You are StudyLens AI, a helpful and knowledgeable study tutor. "
        "Your role is to help students understand their uploaded study material "
        "and prepare for their exams.\n\n"
        "IMPORTANT RULES:\n"
        "1. The student's uploaded STUDY MATERIAL below is your PRIMARY source of truth. "
        "Base your answers on this material first and foremost.\n"
        "2. The SYLLABUS provides context about what topics should be covered.\n"
        "3. If a student asks about a topic that is NOT present in the uploaded material "
        "or context provided, clearly say: \"This topic doesn't appear to be covered "
        "in your uploaded study material.\" Do NOT fabricate information.\n"
        "4. Do not claim information came from the student's material when it did not.\n"
        "5. Give student-friendly explanations. Be concise and clear.\n"
        "6. Use examples where they help understanding.\n"
        "7. When the student asks 'What should I study next?', base your answer on "
        "the knowledge gaps and revision plan provided — do not give generic advice.\n"
        "8. Support these study intents: 'Explain this', 'Simplify this', "
        "'Give an example', 'Give me a hint', 'Test my understanding', "
        "'What should I study next?'\n\n"
        f"{coverage_text}\n\n"
        f"{gaps_text}\n\n"
        f"{revision_text}\n\n"
        "SYLLABUS:\n"
        f"{ctx.syllabus_text}\n\n"
        "STUDENT'S STUDY MATERIAL:\n"
        f"{ctx.study_material_text}"
    )


# ---------------------------------------------------------------------------
# Main tutor response function
# ---------------------------------------------------------------------------


def get_tutor_response(session_id: str, user_message: str, db) -> dict:
    """Get an AI tutor response grounded in the student's study material.

    Loads session context, enforces the message rate limit, calls the Groq
    API, stores both the user message and the AI response, and returns the
    response dict.

    Args:
        session_id:   UUID of a complete analysis session.
        user_message: The student's question or message (non-empty string).
        db:           sqlite3 connection (with row_factory = sqlite3.Row).

    Returns:
        {
            "response":   str,   # The AI tutor's reply
            "session_id": str,
            "message_id": str    # UUID of the stored assistant message
        }

    Raises:
        ValueError:              If user_message is empty.
        TutorContextError:       If session context cannot be loaded.
        TutorMessageLimitError:  If the session has hit the 100-message limit.
        TutorTimeoutError:       If the AI does not respond within 60 s.
        TutorError:              On any other AI service failure.
    """
    # ------------------------------------------------------------------
    # 1. Validate input
    # ------------------------------------------------------------------
    if not user_message or not user_message.strip():
        raise ValueError("user_message must be a non-empty string")

    # ------------------------------------------------------------------
    # 2. Build context (raises TutorContextError on failure)
    # ------------------------------------------------------------------
    ctx = build_tutor_context(session_id, db)

    # ------------------------------------------------------------------
    # 3. Enforce message limit (Requirement 18.4)
    # ------------------------------------------------------------------
    current_count = count_tutor_messages(session_id)
    if current_count >= _MESSAGE_LIMIT_PER_SESSION:
        raise TutorMessageLimitError()

    # ------------------------------------------------------------------
    # 4. Build the messages list for the API call
    # ------------------------------------------------------------------
    system_prompt = _build_system_prompt(ctx)

    messages: List[dict] = [{"role": "system", "content": system_prompt}]

    # Add stored conversation history (chronological)
    messages.extend(ctx.conversation_history)

    # Add the new user message
    messages.append({"role": "user", "content": user_message.strip()})

    # ------------------------------------------------------------------
    # 5. Call the Groq API — same pattern as analyzer.py
    # ------------------------------------------------------------------
    api_key = os.environ.get("GROQ_API_KEY")
    model = os.environ.get("GROQ_MODEL", _DEFAULT_MODEL)
    client = openai.OpenAI(
        api_key=api_key,
        base_url=_GROQ_BASE_URL,
    )

    try:
        api_response = client.chat.completions.create(
            model=model,
            messages=messages,
            timeout=_TUTOR_TIMEOUT,
        )
    except (openai.APITimeoutError, openai.APIConnectionError) as exc:
        logger.warning("Tutor API timeout for session %s: %s", session_id, exc)
        raise TutorTimeoutError()
    except openai.AuthenticationError:
        logger.error("Groq authentication error in tutor: check GROQ_API_KEY")
        raise TutorError("AI service authentication failed. Please check server configuration.")
    except openai.RateLimitError:
        logger.error("Groq rate limit error in tutor for session %s", session_id)
        raise TutorError("AI service rate limit reached. Please try again in a moment.")
    except openai.APIError as exc:
        logger.error("Groq API error in tutor for session %s: %s", session_id, exc)
        raise TutorError(
            f"AI service error: {exc.message if hasattr(exc, 'message') else str(exc)}"
        )

    # ------------------------------------------------------------------
    # 6. Extract response text
    # ------------------------------------------------------------------
    response_text = (
        api_response.choices[0].message.content
        if api_response.choices and api_response.choices[0].message.content
        else ""
    )
    if not response_text:
        raise TutorError("AI tutor returned an empty response")

    # ------------------------------------------------------------------
    # 7. Persist both messages (only on success — Requirement 18.1)
    # ------------------------------------------------------------------
    save_tutor_message(session_id, "user", user_message.strip())
    assistant_message_id = save_tutor_message(session_id, "assistant", response_text)

    return {
        "response": response_text,
        "session_id": session_id,
        "message_id": assistant_message_id,
    }
