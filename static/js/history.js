/**
 * history.js — Session history panel for StudyLens AI
 *
 * Exports:
 *   loadHistory() — fetches and renders the user's past analysis sessions.
 *
 * Security: all API-returned text (course names, dates, scores) is set
 * via textContent — never innerHTML — to prevent XSS.
 */

import { apiFetch } from './api.js';
import { renderReport } from './report.js';
import { renderRevisionPlan } from './revisionPlan.js';

// ---------------------------------------------------------------------------
// Element ID constants — must match templates/index.html exactly
// ---------------------------------------------------------------------------

const IDS = {
  historyPanel:      'history-panel',
  historyList:       'history-list',
  historyEmpty:      'history-empty',
  historyError:      'history-error',
  navShowHistory:    'nav-show-history',
  newFromHistory:    'btn-new-from-history',
  reportPanel:       'report-panel',
};

const ALL_PANELS = [
  'auth-panel',
  'upload-panel',
  'progress-panel',
  'report-panel',
  'history-panel',
];

// ---------------------------------------------------------------------------
// UI helpers
// ---------------------------------------------------------------------------

function _showPanel(panelId) {
  ALL_PANELS.forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.hidden = id !== panelId;
  });
}

function _showHistoryError(message) {
  const el = document.getElementById(IDS.historyError);
  if (!el) return;
  el.textContent = message;
  el.hidden = false;
}

function _clearHistoryError() {
  const el = document.getElementById(IDS.historyError);
  if (!el) return;
  el.textContent = '';
  el.hidden = true;
}

/**
 * Format an ISO 8601 date string into a locale date string.
 * Falls back to the raw string if parsing fails.
 * @param {string} dateStr
 * @returns {string}
 */
function _formatDate(dateStr) {
  if (!dateStr) return '—';
  try {
    return new Date(dateStr).toLocaleDateString(undefined, {
      year: 'numeric', month: 'short', day: 'numeric',
    });
  } catch (_) {
    return dateStr;
  }
}

// ---------------------------------------------------------------------------
// Session card builder
// ---------------------------------------------------------------------------

/**
 * Build a single session card element.
 * All text is set via textContent — no innerHTML for API-returned values.
 *
 * @param {object} session - Session summary from GET /api/sessions
 * @returns {HTMLElement}
 */
function _buildSessionCard(session) {
  const card = document.createElement('div');
  card.className = 'session-card';
  card.setAttribute('role', 'listitem');
  card.setAttribute('tabindex', '0');
  card.setAttribute('aria-label',
    `Session: ${session.course_name || 'Untitled'}, score ${session.readiness_score ?? '—'}%`
  );

  // Course name
  const nameEl = document.createElement('div');
  nameEl.className = 'session-card-title';
  nameEl.textContent = session.course_name || 'Untitled';
  card.appendChild(nameEl);

  // Date
  const dateEl = document.createElement('div');
  dateEl.className = 'session-card-date';
  dateEl.textContent = _formatDate(session.created_at);
  card.appendChild(dateEl);

  // Readiness score badge
  const score = session.readiness_score;
  const scoreBadge = document.createElement('div');
  scoreBadge.className = 'session-card-score';
  if (typeof score === 'number') {
    const badgeClass = score < 50 ? 'score-badge score-badge--danger'
                     : score < 70 ? 'score-badge score-badge--caution'
                     :              'score-badge score-badge--good';
    scoreBadge.className += ` ${badgeClass}`;
    scoreBadge.textContent = `${score}%`;
  } else {
    scoreBadge.textContent = session.status === 'failed' ? 'Failed' : 'Pending';
  }
  card.appendChild(scoreBadge);

  // Coverage summary counts
  const summary = session.coverage_summary;
  if (summary && typeof summary === 'object') {
    const summaryEl = document.createElement('div');
    summaryEl.className = 'session-card-summary';

    const items = [
      { label: 'Covered',  value: summary.covered,           cls: 'count-covered'  },
      { label: 'Partial',  value: summary.partially_covered, cls: 'count-partial'  },
      { label: 'Missing',  value: summary.missing,           cls: 'count-missing'  },
    ];

    items.forEach(({ label, value, cls }) => {
      const item = document.createElement('span');
      item.className = `session-summary-item ${cls}`;
      item.textContent = `${label}: ${value ?? 0}`;
      summaryEl.appendChild(item);
    });

    card.appendChild(summaryEl);
  }

  // Status indicator for non-complete sessions
  if (session.status && session.status !== 'complete') {
    const statusEl = document.createElement('div');
    statusEl.className = `session-card-status session-status--${session.status}`;
    statusEl.textContent = session.status.charAt(0).toUpperCase() + session.status.slice(1);
    card.appendChild(statusEl);
  }

  return card;
}

// ---------------------------------------------------------------------------
// Card click handler — load and render full session detail
// ---------------------------------------------------------------------------

async function _onCardClick(sessionId) {
  _clearHistoryError();

  let detail;
  try {
    detail = await apiFetch('GET', `/api/sessions/${sessionId}`);
  } catch (err) {
    _showHistoryError(
      (err && err.message) ? err.message : 'Could not load session details. Please try again.'
    );
    return;
  }

  if (!detail) {
    _showHistoryError('Session details are unavailable.');
    return;
  }

  // Render the report and revision plan into the report panel
  if (typeof renderReport === 'function') {
    renderReport(detail.full_report ?? detail);
  }
  if (typeof renderRevisionPlan === 'function') {
    renderRevisionPlan(
      detail.revision_plan ?? (detail.full_report && detail.full_report.revision_plan) ?? null
    );
  }

  _showPanel(IDS.reportPanel);
}

// ---------------------------------------------------------------------------
// Public: loadHistory()
// ---------------------------------------------------------------------------

/**
 * Fetch and render the session history panel.
 *
 * Calls GET /api/sessions, builds a card for each session, and injects
 * them into #history-list.  Wires click handlers on each card.
 * Shows #history-empty when the list is empty.
 * Shows #history-error on API failure.
 */
export async function loadHistory() {
  _clearHistoryError();

  const list  = document.getElementById(IDS.historyList);
  const empty = document.getElementById(IDS.historyEmpty);
  if (!list) return;

  // Remove previously injected cards (leave the empty-state p intact)
  Array.from(list.children).forEach((child) => {
    if (child.id !== IDS.historyEmpty) list.removeChild(child);
  });
  if (empty) empty.hidden = true;

  let data;
  try {
    data = await apiFetch('GET', '/api/sessions');
  } catch (err) {
    _showHistoryError(
      (err && err.message) ? err.message : 'Could not load session history. Please try again.'
    );
    return;
  }

  const sessions = (data && Array.isArray(data.sessions)) ? data.sessions : [];

  if (sessions.length === 0) {
    if (empty) empty.hidden = false;
    return;
  }

  sessions.forEach((session) => {
    const card = _buildSessionCard(session);

    // Click handler
    const handleClick = () => _onCardClick(session.id);
    card.addEventListener('click', handleClick);

    // Keyboard: Enter or Space activates the card
    card.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        handleClick();
      }
    });

    list.appendChild(card);
  });
}

// ---------------------------------------------------------------------------
// Initialisation — wires nav and in-panel buttons
// ---------------------------------------------------------------------------

function _init() {
  // "My Sessions" nav button → show history panel and load history
  const navBtn = document.getElementById(IDS.navShowHistory);
  if (navBtn && !navBtn._historyBound) {
    navBtn.addEventListener('click', () => {
      _showPanel(IDS.historyPanel);
      loadHistory();
    });
    navBtn._historyBound = true;
  }

  // "New analysis" button inside history panel → show upload panel
  const newBtn = document.getElementById(IDS.newFromHistory);
  if (newBtn && !newBtn._historyNewBound) {
    newBtn.addEventListener('click', () => {
      const token = sessionStorage.getItem('studylens_token');
      _showPanel(token ? 'upload-panel' : 'auth-panel');
    });
    newBtn._historyNewBound = true;
  }
}

// Auto-initialise when the DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _init);
} else {
  _init();
}
