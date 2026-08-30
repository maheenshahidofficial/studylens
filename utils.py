import os
import pathlib

from flask import current_app
from db import get_db


# ---------------------------------------------------------------------------
# Exception classes
# ---------------------------------------------------------------------------

class UnsupportedMediaError(Exception):
    """Raised when an uploaded file is not a valid PDF. Maps to HTTP 415."""
    def __init__(self, message: str = "Only PDF files are accepted"):
        super().__init__(message)
        self.message = message
        self.status_code = 415


class FileTooLargeError(Exception):
    """Raised when an uploaded file exceeds the size limit. Maps to HTTP 413."""
    def __init__(self, message: str = "File exceeds the 20 MB limit"):
        super().__init__(message)
        self.message = message
        self.status_code = 413


class StorageError(Exception):
    """Raised when a file cannot be saved to disk. Maps to HTTP 500."""
    def __init__(self, message: str = "File could not be saved"):
        super().__init__(message)
        self.message = message
        self.status_code = 500


class RateLimitError(Exception):
    """Raised when the concurrent session limit is reached. Maps to HTTP 429."""
    def __init__(self, message: str = "Maximum of 5 concurrent sessions reached"):
        super().__init__(message)
        self.message = message
        self.status_code = 429


# ---------------------------------------------------------------------------
# Task 5.1 — validate_pdf
# ---------------------------------------------------------------------------

def validate_pdf(file_storage) -> None:
    """Validate that an uploaded file is a PDF and within the size limit.

    Checks the Content-Length header first, then inspects the first 4 bytes
    for the ``%PDF`` magic bytes, and finally measures the actual stream size
    as a fallback for missing Content-Length headers.

    Args:
        file_storage: A Werkzeug ``FileStorage`` object from a Flask request.

    Raises:
        FileTooLargeError: If the file exceeds 20 MB (20,971,520 bytes).
        UnsupportedMediaError: If the file does not begin with the ``%PDF``
            magic bytes.
    """
    # 1. Size check via Content-Length header
    content_length = file_storage.content_length
    if content_length and content_length > 20_971_520:
        raise FileTooLargeError()

    # 2. Magic bytes check — read first 4 bytes then seek back to 0
    header = file_storage.stream.read(4)
    file_storage.stream.seek(0)
    if header != b"%PDF":
        raise UnsupportedMediaError()

    # 3. Stream size check — catches cases where content_length is absent
    file_storage.stream.seek(0, 2)   # seek to end
    stream_size = file_storage.stream.tell()
    file_storage.stream.seek(0)      # reset to start
    if stream_size > 20_971_520:
        raise FileTooLargeError()


# ---------------------------------------------------------------------------
# Task 5.2 — save_upload
# ---------------------------------------------------------------------------

def save_upload(file_storage, student_id: str, session_id: str, filename: str) -> pathlib.Path:
    """Save an uploaded file to the configured upload directory.

    Builds the destination path as ``UPLOAD_ROOT/<student_id>/<session_id>/<filename>``,
    verifies the resolved path is a strict child of ``UPLOAD_ROOT`` to prevent
    path traversal attacks, creates parent directories as needed, and saves
    the file stream to disk.

    Args:
        file_storage: A Werkzeug ``FileStorage`` object from a Flask request.
        student_id: The authenticated user's UUID string.
        session_id: The analysis session UUID string.
        filename: The sanitised filename to write.

    Returns:
        The resolved ``pathlib.Path`` of the saved file.

    Raises:
        StorageError: If the resolved path escapes ``UPLOAD_ROOT`` (path
            traversal), or if an ``IOError`` occurs while writing the file.
    """
    # 1. Resolve UPLOAD_ROOT from Flask app config
    upload_root = pathlib.Path(current_app.config["UPLOAD_ROOT"]).resolve()

    # 2. Build destination path
    dest = upload_root / student_id / session_id / filename
    dest_resolved = dest.resolve()

    # 3. Path traversal check
    if not str(dest_resolved).startswith(str(upload_root) + os.sep):
        raise StorageError("Invalid upload path")

    # 4. Create parent directories
    dest_resolved.parent.mkdir(parents=True, exist_ok=True)

    # 5. Save the file; on IOError discard partial file and re-raise
    try:
        file_storage.save(str(dest_resolved))
    except IOError:
        if dest_resolved.exists():
            dest_resolved.unlink()
        raise StorageError()

    # 6. Return the resolved path
    return dest_resolved


# ---------------------------------------------------------------------------
# Task 5.3 — check_concurrent_limit
# ---------------------------------------------------------------------------

def check_concurrent_limit(student_id: str) -> None:
    """Raise RateLimitError if the student already has 5 or more pending sessions.

    Queries ``analysis_sessions`` using a parameterised placeholder to count
    rows with ``status = 'pending'`` for the given student.  Never concatenates
    user-supplied values directly into SQL.

    Args:
        student_id: The authenticated user's UUID string.

    Raises:
        RateLimitError: If the student has 5 or more concurrent pending sessions.
    """
    db = get_db()
    row = db.execute(
        "SELECT COUNT(*) as cnt FROM analysis_sessions WHERE student_id = ? AND status = 'pending'",
        (student_id,),
    ).fetchone()
    count = row["cnt"] if row else 0

    if count >= 5:
        raise RateLimitError()
