/**
 * upload.js — File upload validation and submission for StudyLens AI
 *
 * Task 11.1: client-side validation (file type + size, button state).
 * Task 11.2: async form submission via apiFetch, progress panel, report rendering.
 */

import { apiFetch } from './api.js';
import { renderReport } from './report.js';
import { renderRevisionPlan } from './revisionPlan.js';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAX_FILE_SIZE = 20 * 1024 * 1024; // 20 MiB in bytes (20,971,520)
const PDF_MIME_TYPE = 'application/pdf';

// Element IDs — must match templates/index.html exactly
const IDS = {
  studyMaterialInput: 'input-study-material',
  studyMaterialError: 'study-material-error',
  syllabusInput:      'input-syllabus',
  syllabusError:      'syllabus-error',
  uploadError:        'upload-error',
  analyzeBtn:         'btn-analyze',
  uploadForm:         'form-upload',
  progressPanel:      'progress-panel',
  progressStatus:     'progress-status',
  reportPanel:        'report-panel',
  courseNameInput:    'input-course-name',
};

// ---------------------------------------------------------------------------
// Validation state — tracks whether each field currently holds a valid file
// ---------------------------------------------------------------------------

const _valid = {
  studyMaterial: false,
  syllabus: false,
};

// ---------------------------------------------------------------------------
// UI helpers
// ---------------------------------------------------------------------------

function _showFieldError(errorId, message) {
  const el = document.getElementById(errorId);
  if (!el) return;
  el.textContent = message;
  el.hidden = false;
}

function _clearFieldError(errorId) {
  const el = document.getElementById(errorId);
  if (!el) return;
  el.textContent = '';
  el.hidden = true;
}

function _showUploadError(message) {
  const el = document.getElementById(IDS.uploadError);
  if (!el) return;
  el.textContent = message;
  el.hidden = false;
}

function _clearUploadError() {
  const el = document.getElementById(IDS.uploadError);
  if (!el) return;
  el.textContent = '';
  el.hidden = true;
}

/** Clear the file input back to empty state (as required on validation failure). */
function _clearFileInput(inputId) {
  const input = document.getElementById(inputId);
  if (input) input.value = '';
}

/** Re-evaluate whether both files are valid and toggle the submit button. */
function _updateSubmitButton() {
  const btn = document.getElementById(IDS.analyzeBtn);
  if (!btn) return;
  btn.disabled = !(_valid.studyMaterial && _valid.syllabus);
}

/** Show a panel by ID and hide all other main panels. */
function _showPanel(panelId) {
  const panels = [
    'auth-panel',
    'upload-panel',
    'progress-panel',
    'report-panel',
    'history-panel',
  ];
  panels.forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.hidden = id !== panelId;
  });
}

/** Update the progress status message. */
function _setProgressStatus(message) {
  const el = document.getElementById(IDS.progressStatus);
  if (el) el.textContent = message;
}

// ---------------------------------------------------------------------------
// Core validation — shared logic for both file inputs
// ---------------------------------------------------------------------------

/**
 * Validate a single file against the PDF type and 20 MiB size constraints.
 *
 * @param {File|null|undefined} file      - The File object from the input.
 * @param {string}              inputId   - Element ID of the file input.
 * @param {string}              errorId   - Element ID of the error container.
 * @param {string}              fieldName - Human-readable field name for messages.
 * @returns {boolean} true if the file is valid; false otherwise.
 */
function _validateFile(file, inputId, errorId, fieldName) {
  // No file selected — clear any prior error, mark invalid
  if (!file) {
    _clearFieldError(errorId);
    return false;
  }

  // Check MIME type
  if (file.type !== PDF_MIME_TYPE) {
    _showFieldError(
      errorId,
      `${fieldName} must be a PDF file. Please select a valid PDF.`
    );
    _clearFileInput(inputId);
    return false;
  }

  // Check file size (≤ 20 MiB)
  if (file.size > MAX_FILE_SIZE) {
    _showFieldError(
      errorId,
      `${fieldName} exceeds the 20 MB limit (${(file.size / 1024 / 1024).toFixed(1)} MB). ` +
      `Please choose a smaller file.`
    );
    _clearFileInput(inputId);
    return false;
  }

  // File is valid — clear any prior error
  _clearFieldError(errorId);
  return true;
}

// ---------------------------------------------------------------------------
// Event handlers
// ---------------------------------------------------------------------------

function _onStudyMaterialChange(event) {
  const file = event.target.files?.[0] ?? null;
  _valid.studyMaterial = _validateFile(
    file,
    IDS.studyMaterialInput,
    IDS.studyMaterialError,
    'Study material'
  );
  _updateSubmitButton();
}

function _onSyllabusChange(event) {
  const file = event.target.files?.[0] ?? null;
  _valid.syllabus = _validateFile(
    file,
    IDS.syllabusInput,
    IDS.syllabusError,
    'Syllabus'
  );
  _updateSubmitButton();
}

/**
 * Task 11.2 — Async form submit handler.
 *
 * 1. Synchronously disables the button and shows the progress panel BEFORE
 *    any async work — satisfying the 300 ms requirement.
 * 2. Builds FormData and calls apiFetch("POST", "/api/analyze", formData).
 * 3. On success: calls renderReport() and renderRevisionPlan(), shows report panel.
 * 4. On error: hides progress panel, shows human-readable error in #upload-error,
 *    re-enables the button if files are still valid.
 */
async function _onFormSubmit(event) {
  event.preventDefault();

  // Guard: abort if validation state is invalid (should not happen if button
  // is properly gated, but defensive check)
  if (!_valid.studyMaterial || !_valid.syllabus) {
    return;
  }

  const btn = document.getElementById(IDS.analyzeBtn);

  // --- SYNCHRONOUS section: must happen before any await ---
  // Disable button immediately to prevent double-submission
  if (btn) btn.disabled = true;
  // Show progress panel immediately (within the same call stack as the click)
  _showPanel(IDS.progressPanel);
  _setProgressStatus('Analysing your study material… This may take up to 60 seconds.');
  _clearUploadError();

  // --- Build FormData ---
  const studyMaterialInput = document.getElementById(IDS.studyMaterialInput);
  const syllabusInput      = document.getElementById(IDS.syllabusInput);
  const courseNameInput    = document.getElementById(IDS.courseNameInput);

  const formData = new FormData();
  formData.append('study_material', studyMaterialInput.files[0]);
  formData.append('syllabus', syllabusInput.files[0]);

  const courseName = courseNameInput?.value?.trim();
  if (courseName) {
    formData.append('course_name', courseName);
  }

  // --- Async: call the API ---
  try {
    const result = await apiFetch('POST', '/api/analyze', formData);
    // Do NOT set Content-Type — apiFetch leaves it unset for FormData bodies

    // Success — render the report and revision plan
    if (typeof renderReport === 'function') {
      renderReport(result);
    }
    if (typeof renderRevisionPlan === 'function') {
      renderRevisionPlan(result.revision_plan);
    }

    // Show the report panel; clear progress
    _setProgressStatus('');
    _showPanel(IDS.reportPanel);

  } catch (err) {
    // Error — hide progress, show human-readable message, re-enable button
    _showPanel('upload-panel');
    _setProgressStatus('');

    // err.message comes from apiFetch which already extracted the backend
    // error string — never contains raw status codes or stack traces
    const message = (err && err.message)
      ? err.message
      : 'Analysis failed. Please try again.';
    _showUploadError(message);

    // Re-enable the button only if files are still valid
    _updateSubmitButton();
  }
}

// ---------------------------------------------------------------------------
// Initialisation
// ---------------------------------------------------------------------------

function _init() {
  const studyMaterialInput = document.getElementById(IDS.studyMaterialInput);
  const syllabusInput      = document.getElementById(IDS.syllabusInput);
  const uploadForm         = document.getElementById(IDS.uploadForm);
  const analyzeBtn         = document.getElementById(IDS.analyzeBtn);

  // Ensure button starts disabled (matches the `disabled` attribute in HTML)
  if (analyzeBtn) analyzeBtn.disabled = true;

  // Reset validation state and clear any stale errors on init
  _valid.studyMaterial = false;
  _valid.syllabus = false;
  _clearFieldError(IDS.studyMaterialError);
  _clearFieldError(IDS.syllabusError);
  _clearUploadError();

  if (studyMaterialInput) {
    studyMaterialInput.addEventListener('change', _onStudyMaterialChange);
  }

  if (syllabusInput) {
    syllabusInput.addEventListener('change', _onSyllabusChange);
  }

  if (uploadForm) {
    uploadForm.addEventListener('submit', _onFormSubmit);
  }
}

// Auto-initialise when the DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _init);
} else {
  _init();
}
