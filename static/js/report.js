/**
 * report.js — Report rendering for StudyLens AI
 *
 * Exports:
 *   renderReport(data) — populates the #report-panel with analysis results.
 *
 * Security: all AI-generated text is set via textContent (never innerHTML)
 * to prevent XSS from arbitrary AI output.
 */

// ---------------------------------------------------------------------------
// Helper: safe text setter — never uses innerHTML for user/AI content
// ---------------------------------------------------------------------------

function _setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text ?? '';
}

function _show(id) {
  const el = document.getElementById(id);
  if (el) el.hidden = false;
}

function _hide(id) {
  const el = document.getElementById(id);
  if (el) el.hidden = true;
}

// ---------------------------------------------------------------------------
// Coverage status helpers
// ---------------------------------------------------------------------------

/** Return a human-readable label for a coverage_status value. */
function _statusLabel(status) {
  switch (status) {
    case 'covered':           return 'Covered';
    case 'partially_covered': return 'Partial';
    case 'missing':           return 'Missing';
    default:                  return status ?? '—';
  }
}

/** Return a CSS class for the coverage badge based on status. */
function _statusClass(status) {
  switch (status) {
    case 'covered':           return 'badge badge-covered';
    case 'partially_covered': return 'badge badge-partial';
    case 'missing':           return 'badge badge-missing';
    default:                  return 'badge';
  }
}

/** Return a human-readable label for an importance value. */
function _importanceLabel(importance) {
  if (!importance) return '—';
  return importance.charAt(0).toUpperCase() + importance.slice(1);
}

// ---------------------------------------------------------------------------
// Section renderers
// ---------------------------------------------------------------------------

/**
 * Render the readiness score and toggle the danger/caution alert banners.
 * @param {number} score - Integer 0–100.
 */
function _renderScore(score) {
  const scoreEl = document.getElementById('readiness-score');
  if (scoreEl) scoreEl.textContent = `${score}%`;

  // Show/hide alert banners based on threshold
  if (score < 50) {
    _show('score-alert-danger');
    _hide('score-alert-caution');
  } else if (score <= 69) {
    _hide('score-alert-danger');
    _show('score-alert-caution');
  } else {
    _hide('score-alert-danger');
    _hide('score-alert-caution');
  }
}

/**
 * Populate the coverage summary counts.
 * @param {object} summary - { total, covered, partially_covered, missing }
 */
function _renderCoverageSummary(summary) {
  if (!summary) return;
  _setText('count-covered', summary.covered ?? 0);
  _setText('count-partial', summary.partially_covered ?? 0);
  _setText('count-missing', summary.missing ?? 0);
}

/**
 * Render extraction/pipeline warnings.
 * @param {string[]} warnings
 */
function _renderWarnings(warnings) {
  const container = document.getElementById('report-warnings');
  if (!container) return;

  if (!warnings || warnings.length === 0) {
    container.hidden = true;
    container.textContent = '';
    return;
  }

  container.textContent = '';
  const ul = document.createElement('ul');
  ul.className = 'warnings-items';
  warnings.forEach((w) => {
    const li = document.createElement('li');
    li.textContent = w;           // AI-generated text — textContent only
    ul.appendChild(li);
  });
  container.appendChild(ul);
  container.hidden = false;
}

/**
 * Render all topics into the topic coverage table body.
 * @param {Array}  topics       - Array of topic objects from the API.
 * @param {number} score        - Readiness score (used to build caution list).
 */
function _renderTopicsTable(topics, score) {
  const tbody = document.getElementById('topics-tbody');
  if (!tbody) return;

  tbody.textContent = ''; // Clear previous rows

  if (!topics || topics.length === 0) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 4;
    td.textContent = 'No topic data available.';
    td.className = 'empty-state';
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  // If score is 50–69, update the caution banner to list partial topics
  if (score >= 50 && score <= 69) {
    const partialTopics = topics
      .filter((t) => t.coverage_status === 'partially_covered')
      .map((t) => t.title)
      .join(', ');
    const cautionEl = document.getElementById('score-alert-caution');
    if (cautionEl && partialTopics) {
      cautionEl.textContent = '';
      const msg = document.createElement('p');
      msg.textContent =
        'Your preparation is partial. Review the following partially covered topics:';
      const list = document.createElement('p');
      list.textContent = partialTopics;     // textContent — never innerHTML
      cautionEl.appendChild(msg);
      cautionEl.appendChild(list);
    }
  }

  topics.forEach((topic) => {
    const tr = document.createElement('tr');

    // Title
    const tdTitle = document.createElement('td');
    tdTitle.textContent = topic.title ?? '—';
    tr.appendChild(tdTitle);

    // Importance
    const tdImportance = document.createElement('td');
    tdImportance.textContent = _importanceLabel(topic.importance);
    tr.appendChild(tdImportance);

    // Coverage status badge
    const tdStatus = document.createElement('td');
    const badge = document.createElement('span');
    badge.className = _statusClass(topic.coverage_status);
    badge.textContent = _statusLabel(topic.coverage_status);
    tdStatus.appendChild(badge);
    tr.appendChild(tdStatus);

    // Reasoning
    const tdReasoning = document.createElement('td');
    tdReasoning.textContent = topic.reasoning ?? '—';  // AI text — textContent
    tr.appendChild(tdReasoning);

    tbody.appendChild(tr);
  });
}

/**
 * Render the ranked knowledge gaps list.
 * @param {Array} gaps - Array of knowledge gap objects from the API.
 */
function _renderKnowledgeGaps(gaps) {
  const container = document.getElementById('gaps-list');
  const emptyMsg  = document.getElementById('gaps-empty');
  if (!container) return;

  // Remove any previously injected gap items (leave the empty-state p intact)
  Array.from(container.children).forEach((child) => {
    if (child.id !== 'gaps-empty') container.removeChild(child);
  });

  if (!gaps || gaps.length === 0) {
    if (emptyMsg) emptyMsg.hidden = false;
    return;
  }

  if (emptyMsg) emptyMsg.hidden = true;

  // Render gaps in the order provided (already ranked by backend)
  gaps.forEach((gap, index) => {
    const item = document.createElement('div');
    item.className = 'gap-item';
    item.setAttribute('role', 'listitem');

    // Gap header row: topic title + badges
    const header = document.createElement('div');
    header.className = 'gap-header';

    const titleEl = document.createElement('span');
    titleEl.className = 'gap-title';
    titleEl.textContent = gap.topic_title ?? `Gap ${index + 1}`;  // textContent

    const statusBadge = document.createElement('span');
    statusBadge.className = _statusClass(gap.coverage_status);
    statusBadge.textContent = _statusLabel(gap.coverage_status);

    const importanceBadge = document.createElement('span');
    importanceBadge.className = `badge badge-importance-${gap.importance ?? 'low'}`;
    importanceBadge.textContent = _importanceLabel(gap.importance);

    header.appendChild(titleEl);
    header.appendChild(statusBadge);
    header.appendChild(importanceBadge);
    item.appendChild(header);

    // Explanation
    if (gap.explanation) {
      const explanation = document.createElement('p');
      explanation.className = 'gap-explanation';
      explanation.textContent = gap.explanation;   // AI text — textContent
      item.appendChild(explanation);
    }

    container.appendChild(item);
  });
}

// ---------------------------------------------------------------------------
// Wire the "New analysis" button
// ---------------------------------------------------------------------------

function _bindNewAnalysisButton() {
  const btn = document.getElementById('btn-new-analysis');
  if (!btn || btn._boundNewAnalysis) return;

  btn.addEventListener('click', () => {
    // Show the upload panel; other panels are hidden
    const panels = [
      'auth-panel', 'upload-panel', 'progress-panel',
      'report-panel', 'history-panel',
    ];
    // Only navigate if user is authenticated (upload-panel is the right dest)
    // auth.js manages auth state — check for token via sessionStorage
    const token = sessionStorage.getItem('studylens_token');
    const target = token ? 'upload-panel' : 'auth-panel';
    panels.forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.hidden = id !== target;
    });
  });

  btn._boundNewAnalysis = true; // Prevent double-binding on re-renders
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Render the full analysis report into the #report-panel.
 *
 * Expected shape of `data` (from POST /api/analyze):
 * {
 *   session_id:       string,
 *   readiness_score:  number,        // 0–100
 *   coverage_summary: { total, covered, partially_covered, missing },
 *   topics:           [ { title, importance, coverage_status, reasoning, key_gaps } ],
 *   knowledge_gaps:   [ { topic_title, importance, coverage_status, explanation, priority_tier } ],
 *   warnings:         string[],
 *   revision_plan:    { ... }        // rendered separately by revisionPlan.js
 * }
 *
 * @param {object} data - Analysis result from the API.
 */
export function renderReport(data) {
  if (!data) return;

  const score = typeof data.readiness_score === 'number' ? data.readiness_score : 0;

  _renderScore(score);
  _renderCoverageSummary(data.coverage_summary);
  _renderWarnings(data.warnings);
  _renderTopicsTable(data.topics, score);
  _renderKnowledgeGaps(data.knowledge_gaps);
  _bindNewAnalysisButton();
}
