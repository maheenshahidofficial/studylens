/**
 * dashboard.js — Student Progress Dashboard for StudyLens AI
 *
 * Renders #dashboard-panel showing the student's most recent analysis
 * result, recent sessions, knowledge gaps, and revision plan summary.
 * Uses the existing GET /api/sessions and GET /api/sessions/<id> APIs.
 *
 * Exposes window.loadDashboard() for cross-module use.
 */

import { apiFetch } from './api.js';

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

let _currentSession = null;

// ---------------------------------------------------------------------------
// DOM helpers
// ---------------------------------------------------------------------------

function _el(id) { return document.getElementById(id); }

function _showPanel(panelId) {
  const panels = [
    'auth-panel', 'upload-panel', 'progress-panel',
    'report-panel', 'history-panel', 'tutor-panel', 'dashboard-panel',
  ];
  panels.forEach((id) => {
    const el = _el(id);
    if (el) el.hidden = id !== panelId;
  });
}

function _setText(id, text) {
  const el = _el(id);
  if (el) el.textContent = text ?? '';
}

function _show(id) { const el = _el(id); if (el) el.hidden = false; }
function _hide(id) { const el = _el(id); if (el) el.hidden = true; }

function _setDashboardError(message) {
  const el = _el('dashboard-error');
  if (!el) return;
  el.textContent = message;
  el.hidden = !message;
}

function _clearDashboardError() { _setDashboardError(''); }

// ---------------------------------------------------------------------------
// Readiness score display helpers
// ---------------------------------------------------------------------------

function _scoreClass(score) {
  if (typeof score !== 'number') return '';
  if (score < 50) return 'score-badge--danger';
  if (score < 70) return 'score-badge--caution';
  return 'score-badge--good';
}

// ---------------------------------------------------------------------------
// Render: latest session summary
// ---------------------------------------------------------------------------

function _renderSummary(session, fullReport) {
  const score = session.readiness_score;
  const scoreEl = _el('dash-score-value');
  if (scoreEl) {
    scoreEl.textContent = typeof score === 'number' ? `${score}%` : '—';
    scoreEl.className = `score-value ${_scoreClass(score)}`;
  }

  // Alert banner
  _hide('dash-alert-danger');
  _hide('dash-alert-caution');
  if (typeof score === 'number') {
    if (score < 50) _show('dash-alert-danger');
    else if (score < 70) _show('dash-alert-caution');
  }

  // Coverage counts
  const cs = session.coverage_summary || {};
  _setText('dash-count-covered',   cs.covered           ?? '—');
  _setText('dash-count-partial',   cs.partially_covered ?? '—');
  _setText('dash-count-missing',   cs.missing           ?? '—');

  // Course name
  _setText('dash-course-name', session.course_name || 'Untitled');

  // Knowledge gaps (top 5 from full report)
  const gapList = _el('dash-gap-list');
  if (gapList) {
    gapList.textContent = '';
    const gaps = (fullReport && fullReport.knowledge_gaps) || [];
    if (gaps.length === 0) {
      const empty = document.createElement('p');
      empty.className = 'empty-state';
      empty.textContent = 'No knowledge gaps — great work!';
      gapList.appendChild(empty);
    } else {
      gaps.slice(0, 5).forEach((gap) => {
        const item = document.createElement('div');
        item.className = 'dash-gap-item';

        const title = document.createElement('span');
        title.className = 'gap-title';
        title.textContent = gap.topic_title || '';

        const badge = document.createElement('span');
        const status = gap.coverage_status || 'missing';
        badge.className = `badge badge-${status === 'missing' ? 'missing' : 'partial'}`;
        badge.textContent = status === 'missing' ? 'Missing' : 'Partial';

        const imp = document.createElement('span');
        imp.className = `badge badge-importance-${gap.importance || 'low'}`;
        imp.textContent = (gap.importance || 'low').charAt(0).toUpperCase() + (gap.importance || 'low').slice(1);

        item.appendChild(title);
        item.appendChild(badge);
        item.appendChild(imp);
        gapList.appendChild(item);
      });
    }
  }

  // Revision plan summary
  const plan = fullReport && fullReport.revision_plan ? fullReport.revision_plan : null;
  if (plan) {
    const taskCount = Array.isArray(plan.tasks) ? plan.tasks.length : 0;
    const totalMins = plan.total_minutes || 0;
    _setText('dash-revision-summary', `${taskCount} task${taskCount !== 1 ? 's' : ''} · ${totalMins} min total`);
    _show('dash-revision-section');
  } else {
    _hide('dash-revision-section');
  }

  // Study Tutor button
  const tutorBtn = _el('btn-dash-open-tutor');
  if (tutorBtn) {
    tutorBtn.onclick = () => {
      if (window.openTutor) window.openTutor(session.id);
    };
  }

  // View full report button
  const reportBtn = _el('btn-dash-view-report');
  if (reportBtn) {
    reportBtn.onclick = () => {
      // Trigger renderReport + renderRevisionPlan with full data then show report panel
      if (fullReport && window.renderReport) window.renderReport(fullReport);
      const planData = fullReport && fullReport.revision_plan ? fullReport.revision_plan : null;
      if (planData && window.renderRevisionPlan) window.renderRevisionPlan(planData);
      _showPanel('report-panel');
    };
  }
}

// ---------------------------------------------------------------------------
// Render: recent sessions list
// ---------------------------------------------------------------------------

function _renderRecentSessions(sessions) {
  const container = _el('dash-recent-sessions');
  if (!container) return;
  container.textContent = '';

  const completed = sessions.filter((s) => s.status === 'complete');
  if (completed.length === 0) return;

  completed.slice(0, 5).forEach((session) => {
    const card = document.createElement('div');
    card.className = 'session-card dash-recent-card';
    card.setAttribute('role', 'button');
    card.setAttribute('tabindex', '0');

    const name = document.createElement('div');
    name.className = 'session-card-title';
    name.textContent = session.course_name || 'Untitled';

    const date = document.createElement('div');
    date.className = 'session-card-date';
    date.textContent = session.created_at
      ? new Date(session.created_at).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
      : '—';

    const score = document.createElement('div');
    score.className = 'session-card-score';
    if (typeof session.readiness_score === 'number') {
      const badge = document.createElement('span');
      badge.className = `score-badge ${_scoreClass(session.readiness_score)}`;
      badge.textContent = `${session.readiness_score}%`;
      score.appendChild(badge);
    }

    card.appendChild(name);
    card.appendChild(date);
    card.appendChild(score);

    const handleClick = () => _selectSession(session.id);
    card.addEventListener('click', handleClick);
    card.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleClick(); }
    });

    container.appendChild(card);
  });
}

// ---------------------------------------------------------------------------
// Select a session and load its full report
// ---------------------------------------------------------------------------

async function _selectSession(sessionId) {
  _clearDashboardError();
  try {
    const data = await apiFetch('GET', `/api/sessions/${sessionId}`);
    if (!data) return;
    _currentSession = data.session;
    const fullReport = data.full_report || {};
    // Merge plan into fullReport for convenience
    if (data.revision_plan) fullReport.revision_plan = data.revision_plan;
    _renderSummary(data.session, fullReport);
    _hide('dash-empty');
    _show('dash-content');
  } catch (err) {
    _setDashboardError(err.message || 'Could not load session details.');
  }
}

// ---------------------------------------------------------------------------
// Public: loadDashboard()
// ---------------------------------------------------------------------------

/**
 * Load and render the student progress dashboard.
 * Fetches sessions, picks the most recent complete one, and renders
 * summary + recent session list.
 */
export async function loadDashboard() {
  _clearDashboardError();
  _hide('dash-content');
  _hide('dash-empty');

  let sessions = [];
  try {
    const data = await apiFetch('GET', '/api/sessions');
    sessions = (data && Array.isArray(data.sessions)) ? data.sessions : [];
  } catch (err) {
    _setDashboardError(err.message || 'Could not load your sessions.');
    return;
  }

  _renderRecentSessions(sessions);

  const completedSessions = sessions.filter((s) => s.status === 'complete');
  if (completedSessions.length === 0) {
    _show('dash-empty');
    return;
  }

  // Select the most recent complete session automatically
  await _selectSession(completedSessions[0].id);
}

// Make available globally
window.loadDashboard = loadDashboard;

// ---------------------------------------------------------------------------
// Initialisation
// ---------------------------------------------------------------------------

function _init() {
  // "New Analysis" button
  const newBtn = _el('btn-dash-new-analysis');
  if (newBtn) {
    newBtn.addEventListener('click', () => _showPanel('upload-panel'));
  }

  // "My Sessions" nav button → show dashboard
  const navHistoryBtn = _el('nav-show-history');
  if (navHistoryBtn && !navHistoryBtn._dashboardBound) {
    navHistoryBtn.addEventListener('click', () => {
      _showPanel('dashboard-panel');
      loadDashboard();
    });
    navHistoryBtn._dashboardBound = true;
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _init);
} else {
  _init();
}
