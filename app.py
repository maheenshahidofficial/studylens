import datetime
import json
import os
import threading
import uuid

from dotenv import load_dotenv

# Load .env before any os.environ.get() calls
load_dotenv()

from flask import Flask, g, jsonify, render_template, request

import auth
from auth import AuthError, ConflictError, ValidationError, require_auth
from analyzer import PipelineError, PipelineTimeoutError, run_analysis
from db import close_db, get_db, init_db
from extraction import ExtractionError, extract
from utils import (
    FileTooLargeError,
    RateLimitError,
    UnsupportedMediaError,
    check_concurrent_limit,
    save_upload,
    validate_pdf,
)


def create_app() -> Flask:
    """Flask application factory.

    Loads configuration from environment variables, initialises the database
    schema on startup, and registers all routes and teardown hooks.
    """
    app = Flask(__name__)

    app.config["SECRET_KEY"] = os.environ.get("JWT_SECRET", "dev-secret-change-me")
    app.config["UPLOAD_ROOT"] = os.environ.get("UPLOAD_ROOT", "./uploads")
    app.config["DATABASE_URL"] = os.environ.get("DATABASE_URL", "studylens.db")

    with app.app_context():
        init_db()

    app.teardown_appcontext(close_db)

    # -----------------------------------------------------------------------
    # Root route — serve the single-page application
    # -----------------------------------------------------------------------

    @app.route("/")
    def index():
        return render_template("index.html")

    # -----------------------------------------------------------------------
    # Task 4.1 — POST /auth/register
    # -----------------------------------------------------------------------

    @app.route("/auth/register", methods=["POST"])
    def register():
        data = request.get_json(silent=True) or {}
        email = data.get("email", "")
        password = data.get("password", "")
        try:
            auth.register(email, password)
            return jsonify({"message": "Account created"}), 201
        except ValidationError as e:
            return jsonify({"error": e.message}), 400
        except ConflictError as e:
            return jsonify({"error": e.message}), 409

    # -----------------------------------------------------------------------
    # Task 4.2 — POST /auth/login
    # -----------------------------------------------------------------------

    @app.route("/auth/login", methods=["POST"])
    def login():
        data = request.get_json(silent=True) or {}
        email = data.get("email", "")
        password = data.get("password", "")
        try:
            token = auth.login(email, password)
            expires_at = (
                datetime.datetime.utcnow() + datetime.timedelta(seconds=86400)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
            return jsonify({"token": token, "expires_at": expires_at}), 200
        except AuthError:
            return jsonify({"error": "Invalid credentials"}), 401

    # -----------------------------------------------------------------------
    # Task 8.1 — POST /api/analyze
    # -----------------------------------------------------------------------

    @app.route("/api/analyze", methods=["POST"])
    @require_auth
    def analyze():
        student_id = g.current_user
        db = get_db()

        # Concurrent session limit check
        try:
            check_concurrent_limit(student_id)
        except RateLimitError as e:
            return jsonify({"error": e.message}), 429

        # Extract and validate file fields
        study_material_file = request.files.get("study_material")
        syllabus_file = request.files.get("syllabus")

        if not study_material_file:
            return jsonify({"error": "Missing required file: study_material"}), 400
        if not syllabus_file:
            return jsonify({"error": "Missing required file: syllabus"}), 400

        # Validate both PDFs (magic bytes + size)
        try:
            validate_pdf(study_material_file)
        except FileTooLargeError as e:
            return jsonify({"error": e.message}), 413
        except UnsupportedMediaError as e:
            return jsonify({"error": e.message}), 415

        try:
            validate_pdf(syllabus_file)
        except FileTooLargeError as e:
            return jsonify({"error": e.message}), 413
        except UnsupportedMediaError as e:
            return jsonify({"error": e.message}), 415

        # Create analysis session row (status=pending)
        session_id = str(uuid.uuid4())
        course_name = request.form.get("course_name", None)

        db.execute(
            """INSERT INTO analysis_sessions
                   (id, student_id, course_name, status, created_at)
               VALUES (?, ?, ?, 'pending', CURRENT_TIMESTAMP)""",
            (session_id, student_id, course_name),
        )
        db.commit()

        # Helper: mark session failed and commit
        def _fail_session(reason: str) -> None:
            db.execute(
                "UPDATE analysis_sessions SET status='failed', failure_reason=? WHERE id=?",
                (reason, session_id),
            )
            db.commit()

        # Save uploaded PDFs to disk
        try:
            study_material_path = save_upload(
                study_material_file, student_id, session_id, "study_material.pdf"
            )
            syllabus_path = save_upload(
                syllabus_file, student_id, session_id, "syllabus.pdf"
            )
        except Exception as e:
            _fail_session(str(e))
            return jsonify({"error": "File could not be saved"}), 500

        # Extract text from study material
        try:
            study_material_result = extract(str(study_material_path))
        except ExtractionError as e:
            _fail_session(e.message)
            app.logger.error("ExtractionError (study material): %s", e.message)
            return jsonify({"error": f"Study material could not be processed: {e.message}"}), 500

        # Extract text from syllabus
        try:
            syllabus_result = extract(str(syllabus_path))
        except ExtractionError as e:
            _fail_session(e.message)
            app.logger.error("ExtractionError (syllabus): %s", e.message)
            return jsonify({"error": f"Syllabus could not be processed: {e.message}"}), 500

        # Insert extracted_texts rows — one per document
        db.execute(
            """INSERT INTO extracted_texts
                   (id, session_id, doc_type, content, char_count, warnings)
               VALUES (?, ?, 'study_material', ?, ?, ?)""",
            (
                str(uuid.uuid4()),
                session_id,
                study_material_result.text,
                study_material_result.char_count,
                json.dumps(study_material_result.warnings),
            ),
        )
        db.execute(
            """INSERT INTO extracted_texts
                   (id, session_id, doc_type, content, char_count, warnings)
               VALUES (?, ?, 'syllabus', ?, ?, ?)""",
            (
                str(uuid.uuid4()),
                session_id,
                syllabus_result.text,
                syllabus_result.char_count,
                json.dumps(syllabus_result.warnings),
            ),
        )
        db.commit()

        # Run AI analysis pipeline
        try:
            result = run_analysis(
                syllabus_text=syllabus_result.text,
                study_material_text=study_material_result.text,
            )
        except PipelineTimeoutError as e:
            reason = f"Pipeline timed out at stage: {e.stage}"
            _fail_session(reason)
            app.logger.error("PipelineTimeoutError: %s", reason)
            return jsonify({"error": "Analysis timed out. Please try again."}), 500
        except PipelineError as e:
            reason = f"Pipeline error at stage '{e.stage}': {e.message}"
            _fail_session(reason)
            app.logger.error("PipelineError: %s", reason)
            return jsonify({"error": "Analysis failed. Please try again."}), 500
        except Exception as e:
            reason = f"Unexpected error: {type(e).__name__}: {e}"
            _fail_session(reason)
            app.logger.exception("Unexpected error in /api/analyze")
            return jsonify({"error": "Analysis failed due to an unexpected error. Please try again."}), 500

        # Mark session complete and persist results
        db.execute(
            """UPDATE analysis_sessions
               SET status='complete',
                   readiness_score=?,
                   coverage_summary_json=?,
                   full_report_json=?,
                   revision_plan_json=?,
                   completed_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (
                result.readiness_score,
                json.dumps(result.coverage_summary),
                json.dumps({
                    "topics": result.topics,
                    "readiness_score": result.readiness_score,
                    "coverage_summary": result.coverage_summary,
                    "knowledge_gaps": result.knowledge_gaps,
                    "warnings": result.warnings,
                }),
                json.dumps(result.revision_plan),
                session_id,
            ),
        )
        db.commit()

        # Return full result — combine all warnings
        all_warnings = (
            study_material_result.warnings
            + syllabus_result.warnings
            + result.warnings
        )

        return jsonify({
            "session_id": session_id,
            "readiness_score": result.readiness_score,
            "coverage_summary": result.coverage_summary,
            "topics": result.topics,
            "knowledge_gaps": result.knowledge_gaps,
            "warnings": all_warnings,
            "revision_plan": result.revision_plan,
        }), 200

    # -----------------------------------------------------------------------
    # Task 9.1 — GET /api/sessions
    # -----------------------------------------------------------------------

    @app.route("/api/sessions", methods=["GET"])
    @require_auth
    def list_sessions():
        """Return up to 100 analysis sessions for the authenticated student.

        Runs the database query in a background thread so we can enforce a
        5-second timeout without relying on Unix-only signal.alarm.  If the
        query does not complete within 5 seconds, 503 is returned with no
        partial data.
        """
        student_id = g.current_user
        db = get_db()

        rows_holder = {}
        error_holder = {}

        def _run_query():
            try:
                rows = db.execute(
                    """SELECT id, course_name, created_at, status,
                              readiness_score, coverage_summary_json
                       FROM analysis_sessions
                       WHERE student_id = ?
                       ORDER BY created_at DESC
                       LIMIT 100""",
                    (student_id,),
                ).fetchall()
                rows_holder["rows"] = rows
            except Exception as exc:  # noqa: BLE001
                error_holder["exc"] = str(exc)

        t = threading.Thread(target=_run_query, daemon=True)
        t.start()
        t.join(timeout=5.0)

        if t.is_alive():
            # Query exceeded 5 seconds — return 503 with no partial data
            return jsonify(
                {"error": "Session history is temporarily unavailable. Please try again."}
            ), 503

        if "exc" in error_holder:
            return jsonify({"error": "Could not retrieve session history."}), 503

        sessions = []
        for row in rows_holder.get("rows", []):
            coverage_summary = None
            if row["coverage_summary_json"]:
                try:
                    coverage_summary = json.loads(row["coverage_summary_json"])
                except (json.JSONDecodeError, TypeError):
                    coverage_summary = None

            sessions.append({
                "id": row["id"],
                "course_name": row["course_name"],
                "created_at": row["created_at"],
                "status": row["status"],
                "readiness_score": row["readiness_score"],
                "coverage_summary": coverage_summary,
            })

        return jsonify({"sessions": sessions}), 200

    # -----------------------------------------------------------------------
    # Task 9.2 — GET /api/sessions/<session_id>
    # -----------------------------------------------------------------------

    @app.route("/api/sessions/<session_id>", methods=["GET"])
    @require_auth
    def get_session(session_id):
        """Return the full report and revision plan for a single session.

        Returns 404 when the session does not exist.
        Returns 403 (with the same "Not found" message as 404) when the
        session belongs to a different student — this prevents enumeration.
        """
        student_id = g.current_user
        db = get_db()

        row = db.execute(
            """SELECT id, student_id, course_name, created_at, status,
                      readiness_score, coverage_summary_json,
                      full_report_json, revision_plan_json
               FROM analysis_sessions
               WHERE id = ?""",
            (session_id,),
        ).fetchone()

        if row is None:
            return jsonify({"error": "Not found"}), 404

        # Return 403 with the same message as 404 — do not reveal existence
        if row["student_id"] != student_id:
            return jsonify({"error": "Not found"}), 403

        def _parse(value):
            """Parse a JSON column value; return None if absent or invalid."""
            if value is None:
                return None
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return None

        return jsonify({
            "session": {
                "id": row["id"],
                "course_name": row["course_name"],
                "created_at": row["created_at"],
                "status": row["status"],
                "readiness_score": row["readiness_score"],
                "coverage_summary": _parse(row["coverage_summary_json"]),
            },
            "full_report": _parse(row["full_report_json"]),
            "revision_plan": _parse(row["revision_plan_json"]),
        }), 200

    # -----------------------------------------------------------------------
    # Task 4.3 — Global error handlers
    # -----------------------------------------------------------------------

    @app.errorhandler(400)
    def bad_request(e):
        return jsonify({"error": "Bad request"}), 400

    @app.errorhandler(401)
    def unauthorized(e):
        return jsonify({"error": "Authentication required"}), 401

    @app.errorhandler(403)
    def forbidden(e):
        return jsonify({"error": "Not found"}), 403

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(409)
    def conflict(e):
        return jsonify({"error": "Conflict"}), 409

    @app.errorhandler(413)
    def payload_too_large(e):
        return jsonify({"error": "File exceeds the 20 MB limit"}), 413

    @app.errorhandler(415)
    def unsupported_media_type(e):
        return jsonify({"error": "Only PDF files are accepted"}), 415

    @app.errorhandler(429)
    def too_many_requests(e):
        return jsonify({"error": "Maximum of 5 concurrent sessions reached"}), 429

    @app.errorhandler(500)
    def internal_server_error(e):
        return jsonify({"error": "An internal error occurred"}), 500

    return app


app = create_app()


if __name__ == "__main__":
    app.run()
