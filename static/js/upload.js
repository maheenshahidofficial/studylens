/**
 * upload.js -- File upload validation and submission for StudyLens AI
 */

import { apiFetch } from './api.js';
import { renderReport } from './report.js';
import { renderRevisionPlan } from './revisionPlan.js';

const MAX_FILE_SIZE = 20 * 1024 * 1024;
const PDF_MIME_TYPE = 'application/pdf';

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

const _valid = {
  studyMaterial: false,
  syllabus: false,
};

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

function _clearFileInput(inputId) {
  const input = document.getElementById(inputId);
  if (input) input.value = '';
}

function _updateSubmitButton() {
  const btn = document.getElementById(IDS.analyzeBtn);
  if (!btn) return;
  btn.disabled = !(_valid.studyMaterial && _valid.syllabus);
}

function _showPanel(panelId) {
  const panels = [
    'auth-panel', 'upload-panel', 'progress-panel',
    'report-panel', 'history-panel',
  ];
  panels.forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.hidden = id !== panelId;
  });
}

function _setProgressStatus(message) {
  const el = document.getElementById(IDS.progressStatus);
  if (el) el.textContent = message;
}

function _validateFile(file, inputId, errorId, fieldName) {
  if (!file) {
    _clearFieldError(errorId);
    return false;
  }
  if (file.type !== PDF_MIME_TYPE) {
    _showFieldError(errorId, `${fieldName} must be a PDF file. Please select a valid PDF.`);
    _clearFileInput(inputId);
    return false;
  }
  if (file.size > MAX_FILE_SIZE) {
    _showFieldError(
      errorId,
      `${fieldName} exceeds the 20 MB limit (${(file.size / 1024 / 1024).toFixed(1)} MB). Please choose a smaller file.`
    );
    _clearFileInput(inputId);
    return false;
  }
  _clearFieldError(errorId);
  return true;
}

function _onStudyMaterialChange(event) {
  const file = event.target.files?.[0] ?? null;
  _valid.studyMaterial = _validateFile(file, IDS.studyMaterialInput, IDS.studyMaterialError, 'Study material');
  _updateSubmitButton();
}

function _onSyllabusChange(event) {
  const file = event.target.files?.[0] ?? null;
  _valid.syllabus = _validateFile(file, IDS.syllabusInput, IDS.syllabusError, 'Syllabus');
  _updateSubmitButton();
}

async function _onFormSubmit(event) {
  event.preventDefault();
  if (!_valid.studyMaterial || !_valid.syllabus) return;

  const btn = document.getElementById(IDS.analyzeBtn);
  if (btn) btn.disabled = true;
  _showPanel(IDS.progressPanel);
  _setProgressStatus('Analysing your study material... This may take up to 60 seconds.');
  _clearUploadError();

  const studyMaterialInput = document.getElementById(IDS.studyMaterialInput);
  const syllabusInput      = document.getElementById(IDS.syllabusInput);
  const courseNameInput    = document.getElementById(IDS.courseNameInput);

  const formData = new FormData();
  formData.append('study_material', studyMaterialInput.files[0]);
  formData.append('syllabus', syllabusInput.files[0]);

  const courseName = courseNameInput?.value?.trim();
  if (courseName) formData.append('course_name', courseName);

  try {
    const result = await apiFetch('POST', '/api/analyze', formData);

    // Store session ID globally so the "Open Tutor" button on the report panel works
    if (result && result.session_id) {
      window._currentReportSessionId = result.session_id;
    }

    if (typeof renderReport === 'function') renderReport(result);
    if (typeof renderRevisionPlan === 'function') renderRevisionPlan(result.revision_plan);

    _setProgressStatus('');
    _showPanel(IDS.reportPanel);

  } catch (err) {
    _showPanel('upload-panel');
    _setProgressStatus('');
    const message = (err && err.message) ? err.message : 'Analysis failed. Please try again.';
    _showUploadError(message);
    _updateSubmitButton();
  }
}

function _init() {
  const studyMaterialInput = document.getElementById(IDS.studyMaterialInput);
  const syllabusInput      = document.getElementById(IDS.syllabusInput);
  const uploadForm         = document.getElementById(IDS.uploadForm);
  const analyzeBtn         = document.getElementById(IDS.analyzeBtn);

  if (analyzeBtn) analyzeBtn.disabled = true;
  _valid.studyMaterial = false;
  _valid.syllabus = false;
  _clearFieldError(IDS.studyMaterialError);
  _clearFieldError(IDS.syllabusError);
  _clearUploadError();

  if (studyMaterialInput) studyMaterialInput.addEventListener('change', _onStudyMaterialChange);
  if (syllabusInput) syllabusInput.addEventListener('change', _onSyllabusChange);
  if (uploadForm) uploadForm.addEventListener('submit', _onFormSubmit);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _init);
} else {
  _init();
}