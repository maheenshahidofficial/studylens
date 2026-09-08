# Implementation Plan: StudyLens AI (MVP)

## Overview

Build StudyLens AI — a Python/Flask Study Intelligence Platform that analyses a student's PDF study material against their course syllabus, produces an exam-readiness report with a personalised revision plan, and provides a context-aware AI Study Tutor grounded in the student's uploaded material. The implementation follows a clean layered structure: project scaffolding → database → auth → file upload → text extraction → AI analysis → API wiring → frontend → tests → deployment.

---

## Tasks

- [x] 1. Project scaffolding and environment setup
  - [x] 1.1 Create the top-level directory structure and all placeholder module files
    - Create `app.py`, `auth.py`, `db.py`, `extraction.py`, `analyzer.py` at project root — empty placeholders only, no application logic
    - Create `static/css/` and `static/js/` directories with empty placeholder files: `base.css`, `layout.css`, `components.css`, `api.js`, `auth.js`, `upload.js`, `report.js`, `revisionPlan.js`, `history.js`
    - Create `templates/` with an empty `index.html`
    - Create `tests/` directory with empty placeholder files: `test_auth.py`, `test_extraction.py`, `test_analyzer.py`, `test_endpoints.py`, `test_properties.py` — all remain empty; no tests are implemented in this task
    - _Requirements: all (structural prerequisite)_

  - [x] 1.2 Create `requirements.txt` with pinned dependencies
    - Include: `flask==3.0.3`, `flask-bcrypt==1.0.1`, `pyjwt==2.8.0`, `pdfplumber==0.11.1`, `pdf2image==1.17.0`, `pytesseract==0.3.13`, `openai==1.30.5`, `pydantic==2.7.1`, `gunicorn==22.0.0`, `hypothesis==6.103.1`, `pytest==8.2.1`, `pytest-flask==1.3.0`
    - Do not add any additional libraries, frameworks, databases, or frontend dependencies beyond this list
    - _Requirements: all (structural prerequisite)_

  - [x] 1.3 Create `.env.example` and `.gitignore`
    - `.env.example` documents the five required environment variables: `JWT_SECRET`, `OPENAI_API_KEY`, `UPLOAD_ROOT`, `DATABASE_URL`, `FLASK_ENV` — with placeholder values and a comment for each
    - `.gitignore` excludes: `.env`, `*.db`, `uploads/`, `__pycache__/`, `.pytest_cache/`
    - _Requirements: all (structural prerequisite)_

- [x] 2. Database schema and helpers (`db.py`)
  - [x] 2.1 Implement `db.py` with connection management and schema initialisation
    - Implement `get_db() -> sqlite3.Connection` — returns a connection with `row_factory = sqlite3.Row`, reading path from `DATABASE_URL` env var (defaulting to `studylens.db`)
    - Implement `init_db()` — runs all four `CREATE TABLE IF NOT EXISTS` statements for `users`, `analysis_sessions`, `extracted_texts`, `session_artifacts`
    - Implement `close_db()` for Flask teardown registration
    - Use parameterised `?` placeholders; no raw SQL string concatenation anywhere in this file
    - _Requirements: 1.5, 2.5, 3.1, 3.2, 7.8, 8.7, 9.1_

  - [x] 2.2 Wire `db.py` into `app.py` Flask application factory
    - Create a minimal `create_app()` factory in `app.py` that loads config from env vars, calls `init_db()`, and registers `close_db()` as a teardown
    - Add a `if __name__ == "__main__"` guard that runs `app.run()`
    - _Requirements: all (structural prerequisite)_

- [x] 3. Auth module — core logic (`auth.py`)
  - [x] 3.1 Implement `register(email, password) -> None`
    - Validate email matches `local-part@domain` format using a regex; raise `ValidationError(400)` if malformed
    - Validate password is between 8 and 128 characters inclusive; raise `ValidationError(400)` with constraint message if outside range
    - Check for duplicate email with a parameterised `SELECT`; raise `ConflictError(409)` if found
    - Hash password with `flask_bcrypt.generate_password_hash` at work factor 12; store only the hash
    - Insert new row into `users` with a `uuid.uuid4()` as `id`; never store or log the plaintext password
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [x] 3.2 Implement `login(email, password) -> str`
    - Look up user by email; raise `AuthError(401)` with "Invalid credentials" if not found
    - Verify password with `flask_bcrypt.check_password_hash`; raise `AuthError(401)` with same message on mismatch (no distinguishing which failed)
    - Build JWT payload `{"sub": user_id, "iat": now, "exp": now + 86400}`, sign with HS256 using `JWT_SECRET` env var
    - Return the signed token string
    - _Requirements: 1.6, 1.7_

  - [x] 3.3 Implement `@require_auth` decorator
    - Extract `Authorization: Bearer <token>` header; return 401 if absent or malformed
    - Decode and verify the JWT using `JWT_SECRET`; return 401 with "Session expired" if `ExpiredSignatureError`, 401 with "Authentication required" for any other error
    - Inject decoded user id into `flask.g.current_user`
    - _Requirements: 1.8, 1.9, 2.8_

- [x] 4. Auth API endpoints (`app.py`)
  - [x] 4.1 Implement `POST /auth/register` route
    - Parse JSON body; call `auth.register()`; return `{"message": "Account created"}` with 201 on success
    - Catch `ValidationError` → 400, `ConflictError` → 409; serialize as `{"error": "<message>"}`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [x] 4.2 Implement `POST /auth/login` route
    - Parse JSON body; call `auth.login()`; return `{"token": "...", "expires_at": "<ISO 8601>"}` with 200 on success
    - Catch `AuthError` → 401; serialize as `{"error": "Invalid credentials"}`
    - _Requirements: 1.6, 1.7_

  - [x] 4.3 Add global error handlers for 400, 401, 403, 404, 409, 413, 415, 429, 500
    - All handlers return `{"error": "<human-readable message>"}` JSON; never return a stack trace, exception class name, or raw status code in the body
    - _Requirements: 10.6, 11.4_

- [x] 5. File upload handling and PDF validation
  - [x] 5.1 Implement PDF validation helper in `app.py` (or a shared `utils.py`)
    - `validate_pdf(file_storage) -> None` — reads first 4 bytes and asserts `%PDF` magic signature; raises `UnsupportedMediaError(415)` if not matched
    - Checks `file_storage.content_length` ≤ 20 971 520 bytes (20 MiB); raises `FileTooLargeError(413)` if exceeded
    - _Requirements: 2.3, 2.4_

  - [x] 5.2 Implement file save helper
    - `save_upload(file_storage, student_id, session_id, filename) -> pathlib.Path`
    - Construct path as `UPLOAD_ROOT / student_id / session_id / filename` using `pathlib.Path`
    - Assert resolved path is a strict child of `UPLOAD_ROOT` before writing (path traversal prevention)
    - On `IOError` during write, discard partial file and raise `StorageError(500)`
    - _Requirements: 2.5, 2.6_

  - [x] 5.3 Implement concurrent session limit check
    - `check_concurrent_limit(student_id) -> None` — queries `analysis_sessions WHERE student_id = ? AND status = 'pending'`; raises `RateLimitError(429)` if count ≥ 5
    - _Requirements: 11.5, 11.6_

- [x] 6. Extraction Engine (`extraction.py`)
  - [x] 6.1 Implement `extract(file_path: str) -> ExtractionResult`
    - Define `ExtractionResult` as a dataclass or namedtuple with fields `text: str`, `char_count: int`, `warnings: list[str]`
    - Step 1: open with `pdfplumber`; raise `ExtractionError` immediately if page count > 500 (Requirement 3.9)
    - Step 2: iterate pages; for each page attempt `pdfplumber` text extraction; collect page text
    - Step 3: for any page returning empty/None text, apply OCR via `pdf2image.convert_from_path` + `pytesseract.image_to_string`; track failed OCR page count
    - Step 4: if all pages failed → raise `ExtractionError("File could not be processed")`
    - Step 5: concatenate all page texts; compute `char_count`; if `char_count < 100` append low-content warning
    - Step 6: if any OCR pages failed, append partial-extraction warning with failed page count
    - Return `ExtractionResult(text, char_count, warnings)`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9_

- [x] 7. AI Analyzer (`analyzer.py`)
  - [x] 7.1 Define Pydantic models for AI response validation
    - `TopicModel`: `title: str`, `importance: Literal["high","medium","low"]`, `coverage_status: Literal["covered","partially_covered","missing"]`, `reasoning: str`, `key_gaps: list[str]`
    - `KnowledgeGapModel`: `topic_title: str`, `importance: Literal["high","medium","low"]`, `coverage_status: Literal["partially_covered","missing"]`, `explanation: str`, `priority_tier: int` (1–6)
    - `AnalysisResponseModel`: `topics: list[TopicModel]` (1–200 items), `readiness_score: int` (0–100), `coverage_summary: CoverageSummaryModel`, `knowledge_gaps: list[KnowledgeGapModel]`
    - `RevisionTaskModel`: `title: str`, `description: str`, `duration_minutes: int`, `gap_ref: str`
    - `RevisionPlanModel`: `tasks: list[RevisionTaskModel]`, `total_minutes: int`, `maintenance_task: RevisionTaskModel | None`
    - _Requirements: 4.1, 4.2, 4.3, 5.1–5.6, 6.1–6.4, 7.2–7.4, 8.1–8.6_

  - [x] 7.2 Implement pure computation helpers
    - `compute_readiness_score(covered: int, total: int) -> int` — returns `round((covered / total) * 100)`
    - `build_coverage_summary(statuses: list[str]) -> dict` — returns `{total, covered, partially_covered, missing}`
    - `rank_knowledge_gaps(gaps: list[dict]) -> list[dict]` — sorts by six-tier priority (missing+high=1 … partially_covered+low=6); stable sort
    - `build_revision_plan(gaps: list[dict]) -> dict` — creates one task per gap with duration 60/30/15 min for high/medium/low; if gaps is empty returns maintenance task with 30 min; sets `total_minutes` to sum of all durations
    - _Requirements: 5.5, 6.2, 7.2, 8.2, 8.4, 8.5, 8.6_

  - [x] 7.3 Implement `run_analysis(syllabus_text: str, study_material_text: str) -> AnalysisResult`
    - Build Call 1 system prompt instructing the model to return a JSON object matching `AnalysisResponseModel`; include both texts in the user message
    - Call `openai.chat.completions.create` with `timeout=60`; on `openai.Timeout` raise `PipelineTimeoutError` (maps to 500, marks session failed)
    - On non-200 OpenAI response or JSON parse failure, raise `PipelineError` with stage name
    - Validate response with Pydantic; on validation failure raise `PipelineError`
    - If `len(topics) < 3`, append sparse-syllabus warning to session
    - Build Call 2 prompt sending `knowledge_gaps` from Call 1 response; apply same timeout/error handling
    - Validate Call 2 response with `RevisionPlanModel`
    - Return structured `AnalysisResult` combining both call outputs
    - Enforce 120-second total pipeline budget via `time.monotonic()` before Call 1; if elapsed > 120 s after either call, raise `PipelineTimeoutError`
    - _Requirements: 4.1–4.7, 5.1–5.6, 6.1–6.5, 7.1–7.9, 8.1–8.8, 11.1, 11.2, 11.3_

- [x] 8. `POST /api/analyze` endpoint — full pipeline wiring
  - [x] 8.1 Implement the `POST /api/analyze` route in `app.py`
    - Apply `@require_auth`; call `check_concurrent_limit(g.current_user)`
    - Extract `study_material` and `syllabus` from `request.files`; return 400 identifying the missing field if either is absent
    - Call `validate_pdf()` on each file; catch and return 415 / 413 as appropriate
    - Create a new `analysis_session` row in SQLite with `status='pending'` and a new UUID; save both PDFs via `save_upload()`
    - Call `extract()` for both files; catch `ExtractionError` → update session to `status='failed'`, store `failure_reason`, return 500
    - Insert two rows into `extracted_texts` (including any warnings)
    - If either extraction has a sparse-syllabus condition (< 3 topics hint is handled in analyzer), pass warnings through
    - Call `run_analysis(syllabus_text, study_material_text)`; catch `PipelineTimeoutError` / `PipelineError` → update session to `status='failed'`, store `failure_reason`, return 500
    - UPDATE `analysis_sessions` with `status='complete'`, `readiness_score`, `coverage_summary_json`, `full_report_json`, `revision_plan_json`, `completed_at`
    - Return 200 with full result JSON as specified in the API design
    - _Requirements: 2.1–2.8, 3.1–3.9, 4.1–4.7, 5.1–5.6, 6.1–6.5, 7.1–7.9, 8.1–8.8, 11.1–11.6_

- [x] 9. Session history endpoints
  - [x] 9.1 Implement `GET /api/sessions` route
    - Apply `@require_auth`; query `analysis_sessions WHERE student_id = ? ORDER BY created_at DESC LIMIT 100`
    - Return `{"sessions": [...]}` with fields: `id`, `course_name`, `created_at`, `status`, `readiness_score`, `coverage_summary` (parsed from JSON column); return empty list if none found
    - If query does not complete within 5 seconds, return 503 without partial data
    - _Requirements: 9.1, 9.2, 9.6_

  - [x] 9.2 Implement `GET /api/sessions/<session_id>` route
    - Apply `@require_auth`; query session by `id`; return 404 if not found
    - If `session.student_id != g.current_user`, return 403 with `{"error": "Not found"}` (intentionally vague — do not reveal existence)
    - Return `{"session": {...}, "full_report": <parsed JSON or null>, "revision_plan": <parsed JSON or null>}`
    - _Requirements: 9.3, 9.4, 9.5_

- [x] 10. Frontend — `index.html` skeleton and auth panel
  - [x] 10.1 Write `index.html` with all panel sections and ES module script tags
    - Include `#nav`, `#auth-panel`, `#upload-panel`, `#progress-panel`, `#report-panel`, `#history-panel` sections
    - Link CSS files (`base.css`, `layout.css`, `components.css`) and JS modules with `type="module"`
    - All form inputs have `<label>` elements; all buttons have accessible text or `aria-label`
    - Error/status containers use `role="status"` live regions
    - _Requirements: 10.1, 10.7_

  - [x] 10.2 Implement `auth.js` — register, login, logout
    - `register(email, password)` — POST to `/auth/register`; show success or field-level error
    - `login(email, password)` — POST to `/auth/login`; store JWT in `sessionStorage`; show auth-required panels
    - `logout()` — clear `sessionStorage`, hide authenticated panels, show auth panel
    - Export `getToken()` for use by `api.js`
    - _Requirements: 1.1, 1.6, 1.7, 10.6_

  - [x] 10.3 Implement `api.js` — fetch wrapper
    - `apiFetch(path, options)` — attaches `Authorization: Bearer <token>` header from `sessionStorage`; normalises error responses by reading the `error` field; never exposes raw status codes or stack traces to UI code
    - _Requirements: 10.6_

- [x] 11. Frontend — upload form with client-side validation (`upload.js`)
  - [x] 11.1 Implement client-side file validation in `upload.js`
    - On file input change, check `file.type === "application/pdf"`; display field-specific error if not and prevent form submission
    - Check `file.size <= 20971520`; display error with size limit if exceeded; restore input to empty state
    - Enable submit button only when both files pass all validations; disable on page load
    - _Requirements: 10.2, 10.8_

  - [x] 11.2 Implement upload submission in `upload.js`
    - On submit: disable submit button synchronously; show `#progress-panel` within the same click handler (before the async fetch starts, satisfying the 300 ms requirement)
    - Build `FormData` with `study_material` and `syllabus` fields; call `apiFetch("POST", "/api/analyze", formData)`
    - On success, pass result to `report.js` and `revisionPlan.js` render functions; hide progress panel; show report panel
    - On error, hide progress panel; display human-readable error message from `error` field; re-enable submit button
    - _Requirements: 10.3, 10.4, 10.5, 10.6_

- [x] 12. Frontend — report rendering (`report.js`, `revisionPlan.js`)
  - [x] 12.1 Implement `report.js` — readiness score and topic coverage table
    - `renderReport(data)` — display `readiness_score` prominently; render a table of all topics with columns: title, importance, coverage status badge, reasoning
    - If `readiness_score < 50`, render a prominent alert ("review missing and partially covered topics")
    - If `readiness_score` is 50–69 inclusive, render a caution notice listing partially covered topics
    - Render the ranked knowledge gap list with explanation text for each gap
    - _Requirements: 7.2, 7.3, 7.4, 7.5, 7.6, 10.4_

  - [x] 12.2 Implement `revisionPlan.js` — revision task list
    - `renderRevisionPlan(plan)` — render each task with title, description, and `duration_minutes`; render `total_minutes` as a summary line
    - _Requirements: 8.2, 8.3, 8.4, 8.5, 10.5_

- [x] 13. Frontend — session history panel (`history.js`)
  - [x] 13.1 Implement `history.js` — fetch and render session history
    - `loadHistory()` — GET `/api/sessions`; render each session as a card showing course name (or "Untitled"), upload date, readiness score badge, coverage summary counts
    - On click of a session card, GET `/api/sessions/<id>`; call `renderReport()` and `renderRevisionPlan()` with the returned data; switch to report panel
    - On backend error, display human-readable message; never show raw HTTP status
    - _Requirements: 9.1, 9.2, 9.3, 10.6_

- [x] 14. CSS — responsive layout and components
  - [x] 14.1 Implement `base.css` — reset, CSS variables, typography
    - Define CSS custom properties for colour palette meeting WCAG 2.1 AA (≥ 4.5:1 for normal text, ≥ 3:1 for large text and UI components)
    - Apply a minimal CSS reset; set base font, line-height, and box-sizing
    - _Requirements: 10.1, 10.7_

  - [x] 14.2 Implement `layout.css` — responsive grid at three breakpoints
    - Default (≤ 375 px): single-column stacked layout; no horizontal overflow
    - 768 px: two-column (form + status side-by-side)
    - 1280 px: three-column (nav + main + history sidebar)
    - All interactive elements `min-height: 44px`; no horizontal scrollbar at any breakpoint
    - _Requirements: 10.1_

  - [x] 14.3 Implement `components.css` — cards, badges, tables, alerts, focus rings
    - Coverage status badges: distinct colours for `covered`, `partially_covered`, `missing`
    - Alert and caution notice styles for readiness score thresholds
    - Visible focus rings on all interactive elements
    - Form input and button styles meeting touch-target size requirement
    - _Requirements: 10.1, 10.7_

- [x] 15. Property-based tests — Hypothesis (6 properties)
  - [x]* 15.1 Write property test for Property 1 — Readiness Score formula
    - Use `@given(total=st.integers(1,200), covered=st.integers(0,200))` with `covered = min(covered, total)`
    - Assert `compute_readiness_score(covered, total) == round((covered / total) * 100)`
    - `@settings(max_examples=100)`
    - **Property 1: Readiness Score Formula**
    - **Validates: Requirements 7.2**
    - _Requirements: 7.2_

  - [x]* 15.2 Write property test for Property 2 — Coverage counts sum to total
    - Use `@given(st.lists(st.sampled_from(["covered","partially_covered","missing"]), min_size=1, max_size=200))`
    - Assert `summary["covered"] + summary["partially_covered"] + summary["missing"] == summary["total"]`
    - **Property 2: Coverage Counts Sum to Total**
    - **Validates: Requirements 5.5**
    - _Requirements: 5.5_

  - [x]* 15.3 Write property test for Property 3 — Knowledge Gap six-tier priority order
    - Define a `gap_strategy()` composite strategy producing dicts with random `coverage_status` and `importance`
    - Use `@given(st.lists(gap_strategy(), min_size=1, max_size=50))`
    - Assert for every adjacent pair in `rank_knowledge_gaps(gaps)` that `priority_tier(ranked[i]) <= priority_tier(ranked[i+1])`
    - **Property 3: Knowledge Gaps Follow the Six-Tier Priority Order**
    - **Validates: Requirements 6.2, 8.2**
    - _Requirements: 6.2, 8.2_

  - [x]* 15.4 Write property test for Property 4 — Revision plan total equals sum of durations
    - Define a `task_strategy()` composite strategy producing dicts with random `duration_minutes`
    - Use `@given(st.lists(task_strategy(), min_size=0, max_size=200))`
    - Assert `plan["total_minutes"] == sum(t["duration_minutes"] for t in tasks)`
    - **Property 4: Revision Plan Total Equals Sum of Task Durations**
    - **Validates: Requirements 8.5**
    - _Requirements: 8.5_

  - [x]* 15.5 Write unit test for Property 5 — Passwords never stored in plaintext
    - Call `auth.register()` with a known password; query `users` table directly; assert stored `password_hash != password` and `password_hash.startswith("$2b$")`
    - **Property 5: Passwords Are Never Stored in Plaintext**
    - **Validates: Requirements 1.5**
    - _Requirements: 1.5_

  - [x]* 15.6 Write unit test for Property 6 — Cross-student session access returns 403
    - Register two users A and B; have user A create a session; authenticate as user B and GET `/api/sessions/<session_id>`; assert 403 and body `{"error": "Not found"}`
    - **Property 6: Cross-Student Session Access Returns 403**
    - **Validates: Requirements 9.4**
    - _Requirements: 9.4_

- [ ] 16. Unit tests — pytest
  - [ ]* 16.1 Write unit tests for auth registration (`test_auth.py`)
    - Duplicate email → 409; password at boundaries (7, 8, 128, 129 chars); malformed email formats (no @, no domain, leading dot)
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [ ]* 16.2 Write unit tests for auth login (`test_auth.py`)
    - Correct credentials → JWT with valid `exp` field; wrong password → 401; unknown email → 401; same 401 message for both failures
    - Expired token → 401 with "Session expired" message
    - _Requirements: 1.6, 1.7, 1.9_

  - [ ]* 16.3 Write unit tests for file upload validation (`test_endpoints.py`)
    - Missing `study_material` field → 400 identifying missing field; missing `syllabus` field → 400; non-PDF magic bytes → 415; file exactly 20 MiB → accepted; file 20 MiB + 1 byte → 413
    - Unauthenticated upload → 401
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.8_

  - [ ]* 16.4 Write unit tests for extraction engine (`test_extraction.py`)
    - Embedded-text PDF → no OCR called, text returned; image-only PDF → OCR called; mixed PDF → both paths used, results concatenated
    - All pages failed → `ExtractionError`; `char_count < 100` → low-content warning present; page count > 500 → error
    - Some pages failed → partial-extraction warning with correct failed-page count
    - _Requirements: 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9_

  - [ ]* 16.5 Write unit tests for AI analyzer (`test_analyzer.py`)
    - Mock OpenAI client; verify Call 1 and Call 2 are made in sequence
    - `openai.Timeout` on Call 1 → session marked failed, 500 returned
    - Invalid JSON from AI → `PipelineError` raised
    - Sparse syllabus (< 3 topics) → warning recorded in session
    - _Requirements: 4.5, 4.6, 4.7, 11.2, 11.3_

  - [ ]* 16.6 Write unit tests for session history endpoints (`test_endpoints.py`)
    - Sessions returned descending by `created_at`; capped at 100; returns empty list with no sessions
    - 403 on cross-student access (response body intentionally vague); 404 for unknown session ID
    - _Requirements: 9.1, 9.2, 9.4, 9.5_

- [x] 17. Deployment — Dockerfile and render.yaml
  - [x] 17.1 Write `Dockerfile` for production deployment
    - Base image: `python:3.11-slim`
    - Install system packages: `tesseract-ocr`, `poppler-utils` via `apt-get`; clean apt cache in same layer
    - `COPY . /app`, `WORKDIR /app`, `RUN pip install --no-cache-dir -r requirements.txt`
    - `CMD ["gunicorn", "app:app", "--timeout", "120", "--workers", "1", "--bind", "0.0.0.0:$PORT"]`
    - _Requirements: all (deployment prerequisite)_

  - [x] 17.2 Write `render.yaml` for Render free-tier deployment
    - Service type: `web`, runtime: `docker`, build from `Dockerfile`
    - Define environment variables: `JWT_SECRET` (sync from Render secret), `OPENAI_API_KEY` (sync from Render secret), `UPLOAD_ROOT=/data/uploads`, `DATABASE_URL=/data/studylens.db`, `FLASK_ENV=production`
    - Attach a persistent disk mounted at `/data`
    - _Requirements: all (deployment prerequisite)_

- [x] 18. Database schema extension — tutor messages table
  - [x] 18.1 Add `tutor_messages` table to `db.py`
    - Add `CREATE TABLE IF NOT EXISTS tutor_messages (id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES analysis_sessions(id), role TEXT NOT NULL, content TEXT NOT NULL, created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)` to `init_db()`
    - Verify `session_artifacts` table is already created by `init_db()` (it was defined in Task 2.1)
    - Add helper `get_tutor_messages(session_id, limit=10) -> list` — returns the most recent N messages ordered by `created_at` ASC
    - Add helper `save_tutor_message(session_id, role, content) -> str` — inserts a row, returns the new message UUID
    - Add helper `count_tutor_messages(session_id) -> int` — returns message count for rate-limit enforcement
    - Use parameterised `?` placeholders throughout; no raw SQL string concatenation
    - _Requirements: 12.4, 12.9, 18.4_

- [x] 19. AI Study Tutor backend (`tutor.py`)
  - [x] 19.1 Create `tutor.py` module with context-building and response generation
    - Define `TutorContext` dataclass: `syllabus_text`, `study_material_text`, `coverage_summary`, `knowledge_gaps`, `revision_plan`, `conversation_history`
    - Implement `build_tutor_context(session_id, db) -> TutorContext` — loads extracted texts, full_report_json, revision_plan_json, and last 10 tutor messages from DB
    - Build system prompt grounding the tutor in the student's material; instruct the model to acknowledge when a topic is not in the uploaded material
    - Truncate study material to 40,000 chars and syllabus to 10,000 chars if they exceed those limits
    - Handle "What should I study next?" by deriving the answer from ranked knowledge gaps
    - _Requirements: 12.2, 12.3, 12.5, 12.6, 12.7_

  - [x] 19.2 Implement `get_tutor_response(session_id, user_message, db) -> dict`
    - Call `build_tutor_context()` to load session context
    - Check `count_tutor_messages(session_id)` ≥ 100; if so raise `TutorMessageLimitError(429)`
    - Call Groq API using the same `openai.OpenAI(api_key=..., base_url=...)` pattern from `analyzer.py` with 60-second timeout
    - On success: call `save_tutor_message(session_id, 'user', user_message)` and `save_tutor_message(session_id, 'assistant', response_text)`
    - Return `{"response": response_text, "session_id": session_id, "message_id": assistant_message_id}`
    - On `APITimeoutError` / `APIConnectionError`: raise `TutorTimeoutError(408)` without saving messages
    - On `APIError`: raise `TutorError(500)` without saving messages
    - Never modify `analysis_sessions.full_report_json`, `revision_plan_json`, `readiness_score`, or `coverage_summary_json`
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.8, 12.9, 18.1, 18.2, 18.3_

- [x] 20. AI Study Tutor API endpoints (`app.py`)
  - [x] 20.1 Implement `POST /api/sessions/<session_id>/tutor`
    - Apply `@require_auth`; load session; return 404 if not found, 403 if wrong student, 400 if session not `complete`
    - Parse JSON body; validate `message` field is non-empty string; return 400 if missing
    - Call `tutor.get_tutor_response(session_id, message, db)`
    - Catch `TutorMessageLimitError` → 429, `TutorTimeoutError` → 408, `TutorError` → 500
    - Return 200 with tutor response JSON
    - _Requirements: 12.1, 12.8, 12.10, 18.3, 18.4_

  - [x] 20.2 Implement `GET /api/sessions/<session_id>/tutor/history`
    - Apply `@require_auth`; load session; return 404/403 as appropriate
    - Query `tutor_messages WHERE session_id = ? ORDER BY created_at ASC`
    - Return `{"messages": [...]}` with `id`, `role`, `content`, `created_at` fields
    - _Requirements: 12.4_

- [x] 21. AI Study Tutor frontend (`tutor.js`, `index.html` update)
  - [x] 21.1 Add `#tutor-panel` section to `index.html`
    - Add a new panel with: session context header (course name, readiness score), scrollable message list (`#tutor-messages`), text input (`#tutor-input`), send button (`#btn-tutor-send`)
    - Add four quick-prompt buttons: "Explain this", "Simplify", "Give an example", "What should I study next?"
    - All interactive elements must have `<label>` or `aria-label`; message list uses `role="log"` live region
    - Add link from `#report-panel` to the tutor panel for the same session
    - _Requirements: 12.6, 10.1, 10.7_

  - [x] 21.2 Implement `tutor.js`
    - `openTutor(sessionId)` — load tutor history via `GET /api/sessions/<id>/tutor/history`, render messages in `#tutor-messages`, show tutor panel
    - `sendTutorMessage(sessionId, message)` — POST to `/api/sessions/<id>/tutor`, append user message immediately (optimistic), append AI response on success
    - Wire send button click and Enter key to `sendTutorMessage`
    - Wire quick-prompt buttons to pre-fill and submit the message input
    - On error: display human-readable message in the panel; never show raw HTTP codes
    - Export `openTutor` for use by `report.js` and `dashboard.js`
    - _Requirements: 12.1, 12.6, 10.6_

- [x] 22. Student Progress Dashboard (`dashboard.js`, `index.html` update)
  - [x] 22.1 Add `#dashboard-panel` section to `index.html`
    - Add panel showing: readiness score for most recent session, coverage summary (covered/partial/missing counts), top 3 knowledge gaps list, revision plan summary (total minutes, task count), recent sessions list (up to 5 cards), "Open AI Tutor" button, "New Analysis" button
    - Show prompt to upload study material if no complete session exists
    - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5_

  - [x] 22.2 Implement `dashboard.js`
    - `loadDashboard()` — GET `/api/sessions`; find the most recent complete session; render all dashboard elements
    - Render readiness score with appropriate danger/caution/good colour class
    - Render recent session cards (reuse session-card pattern from `history.js`)
    - Wire "Open AI Tutor" button to `openTutor(sessionId)` from `tutor.js`
    - Wire nav button `#nav-show-dashboard` to show dashboard panel and call `loadDashboard()`
    - Export `loadDashboard`
    - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6_

  - [x] 22.3 Update navigation in `index.html` and `auth.js`
    - Add `#nav-show-dashboard` button to `#nav-user-links`
    - After login success in `auth.js`, show `#dashboard-panel` instead of `#upload-panel` as the post-login default
    - _Requirements: 17.1, 10.6_

- [x] 23. CSS — tutor and dashboard components
  - [x] 23.1 Add tutor chat styles to `components.css`
    - `.tutor-messages` — scrollable message list container with max-height
    - `.tutor-message--user` / `.tutor-message--assistant` — distinct visual styles for each role
    - `.tutor-quick-prompts` — flex row of quick-prompt buttons
    - `.tutor-input-row` — input + send button layout
    - _Requirements: 10.1, 10.7_

  - [x] 23.2 Add dashboard styles to `components.css`
    - `.dashboard-summary` — readiness score + coverage summary row
    - `.dashboard-recent` — recent sessions list
    - `.dashboard-empty` — empty state prompt
    - _Requirements: 10.1, 10.7_

- [ ] 24. Secondary features — Quiz, Viva, Past Paper (DEFERRED — implement after core MVP)
  - [ ]* 24.1 Implement quiz generation in `tutor.py`
    - `generate_quiz(session_id, question_count, difficulty, question_type, db) -> dict`
    - Build prompt from study material text prioritising `missing`/`partially_covered` topics
    - Validate response with Pydantic `QuizModel`; store in `session_artifacts` with `artifact_type='quiz'`
    - Add `POST /api/sessions/<id>/quiz` endpoint in `app.py`
    - Add `quiz.js` frontend module for rendering and answering quiz questions
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5_

  - [ ]* 24.2 Implement viva mode in `tutor.py`
    - `start_viva(session_id, db) -> dict` — generate opening question; store viva state in `session_artifacts`
    - `evaluate_viva_answer(session_id, answer, db) -> dict` — evaluate answer, return feedback and follow-up
    - Add `POST /api/sessions/<id>/viva/start` and `POST /api/sessions/<id>/viva/answer` endpoints
    - Add `viva.js` frontend module
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5_

  - [ ]* 24.3 Implement past paper analysis in `tutor.py` or `analyzer.py`
    - Accept past paper PDF upload via `POST /api/sessions/<id>/past-paper`
    - Extract text using existing `extraction.py`; call AI to identify tested topics
    - Produce adjusted revision priority list; store as `session_artifacts` with `artifact_type='past_paper_analysis'`
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5_

  - [ ]* 24.4 Implement knowledge map generation and rendering
    - Generate node/edge JSON from existing topics and relationships via AI; store as `session_artifact`
    - Add `GET /api/sessions/<id>/artifacts` endpoint
    - Add `knowledgeMap.js` to render the graph using lightweight SVG/Canvas
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5_

---

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP; all core implementation tasks must be completed first.
- Each task references specific requirements for traceability.
- The two checkpoints (after auth and after wiring) let the developer validate incrementally before building the full frontend.
- Property-based tests (15.1–15.4) use Hypothesis with `max_examples=100`; Properties 5 and 6 are unit tests because their input spaces are small and deterministic.
- The `session_artifacts` table is created in task 2.1 but not used in any MVP endpoint — it is reserved for future features (quizzes, flashcards, past papers).
- `UPLOAD_ROOT` and `DATABASE_URL` default to relative paths for local dev; in production they point to the Render persistent disk at `/data`.
- Tasks 18–23 are core MVP additions. Implement after Tasks 1–17 are verified working.
- Task 24 subtasks are marked `*` (optional/secondary). Implement after Tasks 18–23 are stable.
- `tutor.py` reuses the same Groq API pattern from `analyzer.py` — no new AI provider setup needed.
- Context-building in Task 19 uses plain SQL queries; no vector database or embedding infrastructure is required.
- The `session_artifacts` table (created in Task 2.1) is ready for use by Tasks 24.1–24.4 with no schema migration needed.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["2.2"] },
    { "id": 3, "tasks": ["3.1", "3.2", "3.3"] },
    { "id": 4, "tasks": ["4.1", "4.2", "4.3"] },
    { "id": 5, "tasks": ["5.1", "5.2", "5.3"] },
    { "id": 6, "tasks": ["6.1"] },
    { "id": 7, "tasks": ["7.1"] },
    { "id": 8, "tasks": ["7.2"] },
    { "id": 9, "tasks": ["7.3"] },
    { "id": 10, "tasks": ["8.1"] },
    { "id": 11, "tasks": ["9.1", "9.2"] },
    { "id": 12, "tasks": ["10.1", "14.1"] },
    { "id": 13, "tasks": ["10.2", "10.3", "14.2", "14.3"] },
    { "id": 14, "tasks": ["11.1"] },
    { "id": 15, "tasks": ["11.2"] },
    { "id": 16, "tasks": ["12.1", "12.2"] },
    { "id": 17, "tasks": ["13.1"] },
    { "id": 18, "tasks": ["15.1", "15.2", "15.3", "15.4", "15.5", "15.6", "16.1", "16.2", "16.3", "16.4", "16.5", "16.6"] },
    { "id": 19, "tasks": ["17.1"] },
    { "id": 20, "tasks": ["17.2"] },
    { "id": 21, "tasks": ["18.1"] },
    { "id": 22, "tasks": ["19.1"] },
    { "id": 23, "tasks": ["19.2"] },
    { "id": 24, "tasks": ["20.1", "20.2"] },
    { "id": 25, "tasks": ["21.1"] },
    { "id": 26, "tasks": ["21.2"] },
    { "id": 27, "tasks": ["22.1"] },
    { "id": 28, "tasks": ["22.2", "22.3", "23.1", "23.2"] },
    { "id": 29, "tasks": ["24.1", "24.2", "24.3", "24.4"] }
  ]
}
```
