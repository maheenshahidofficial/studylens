/**
 * tutor.js — AI Study Tutor frontend for StudyLens AI
 *
 * Handles the #tutor-panel: loading conversation history, sending messages,
 * rendering user/assistant bubbles, and quick-action prompts.
 *
 * Uses apiFetch from api.js for authenticated requests.
 * Exposes window.openTutor(sessionId) for cross-module access.
 */

import { apiFetch } from './api.js';

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

let _currentSessionId = null;
let _isSending = false;

// Quick-action prompt text — each maps to a pre-filled message
const QUICK_PROMPTS = [
  { label: 'Explain this',           text: 'Please explain the most important concept from my study material in simple terms.' },
  { label: 'Simplify this',          text: 'Can you simplify the hardest topic from my study material so it is easier to understand?' },
  { label: 'Give an example',        text: 'Can you give me a concrete real-world example of one of the key concepts in my study material?' },
  { label: 'Give me a hint',         text: 'I am struggling with one of my knowledge gaps. Can you give me a hint to help me understand it better without giving away the full answer?' },
  { label: 'Test my understanding',  text: 'Can you ask me a question to test my understanding of one of the topics in my study material? Start with something from my knowledge gaps.' },
  { label: 'What should I study next?', text: 'What should I study next based on my knowledge gaps and revision plan?' },
];

// ---------------------------------------------------------------------------
// DOM helpers
// ---------------------------------------------------------------------------

function _el(id) {
  return document.getElementById(id);
}

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

function _scrollToBottom() {
  const msgs = _el('tutor-messages');
  if (msgs) msgs.scrollTop = msgs.scrollHeight;
}

/** Safely create a text node — never uses innerHTML for user content. */
function _createTextEl(tag, text, className) {
  const el = document.createElement(tag);
  el.className = className;
  el.textContent = text;
  return el;
}

function _setTutorError(message) {
  const el = _el('tutor-error');
  if (!el) return;
  el.textContent = message;
  el.hidden = !message;
}

function _clearTutorError() {
  _setTutorError('');
}

function _setSendingState(sending) {
  _isSending = sending;
  const btn = _el('btn-tutor-send');
  const input = _el('tutor-input');
  const loading = _el('tutor-loading');
  if (btn) btn.disabled = sending;
  if (input) input.disabled = sending;
  if (loading) loading.hidden = !sending;
}

// ---------------------------------------------------------------------------
// Message rendering
// ---------------------------------------------------------------------------

/**
 * Append a single message bubble to #tutor-messages.
 * Uses textContent for all user/AI-generated text — no innerHTML.
 */
function _appendMessage(role, content) {
  const container = _el('tutor-messages');
  if (!container) return;

  const wrapper = document.createElement('div');
  wrapper.className = `tutor-message tutor-message--${role}`;

  const label = document.createElement('span');
  label.className = 'tutor-message-label';
  label.textContent = role === 'user' ? 'You' : 'StudyLens AI';

  const bubble = document.createElement('div');
  bubble.className = 'tutor-message-bubble';
  // Split on newlines to preserve line breaks safely without innerHTML
  content.split('\n').forEach((line, i, arr) => {
    bubble.appendChild(document.createTextNode(line));
    if (i < arr.length - 1) bubble.appendChild(document.createElement('br'));
  });

  wrapper.appendChild(label);
  wrapper.appendChild(bubble);
  container.appendChild(wrapper);
  _scrollToBottom();
}

function _clearMessages() {
  const container = _el('tutor-messages');
  if (container) container.textContent = '';
}

// ---------------------------------------------------------------------------
// API calls
// ---------------------------------------------------------------------------

async function _loadHistory(sessionId) {
  try {
    const data = await apiFetch('GET', `/api/sessions/${sessionId}/tutor/history`);
    if (data && Array.isArray(data.messages)) {
      data.messages.forEach((msg) => _appendMessage(msg.role, msg.content));
    }
  } catch (err) {
    // History load failure is non-fatal — show empty state gracefully
    console.warn('Could not load tutor history:', err.message);
  }
}

async function _sendMessage(sessionId, messageText) {
  if (_isSending || !messageText.trim()) return;

  _clearTutorError();
  _setSendingState(true);

  // Optimistic render of the user's message
  _appendMessage('user', messageText.trim());

  try {
    const data = await apiFetch(
      'POST',
      `/api/sessions/${sessionId}/tutor`,
      { message: messageText.trim() },
    );
    if (data && data.response) {
      _appendMessage('assistant', data.response);
    }
  } catch (err) {
    _setTutorError(err.message || 'Something went wrong. Please try again.');
  } finally {
    _setSendingState(false);
    const input = _el('tutor-input');
    if (input) {
      input.value = '';
      input.focus();
    }
  }
}

// ---------------------------------------------------------------------------
// Quick prompts
// ---------------------------------------------------------------------------

function _buildQuickPrompts() {
  const container = _el('tutor-quick-prompts');
  if (!container) return;
  container.textContent = '';

  QUICK_PROMPTS.forEach(({ label, text }) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn-quick-prompt';
    btn.textContent = label;
    btn.addEventListener('click', () => {
      if (_isSending || !_currentSessionId) return;
      _sendMessage(_currentSessionId, text);
    });
    container.appendChild(btn);
  });
}

// ---------------------------------------------------------------------------
// Public: openTutor(sessionId)
// ---------------------------------------------------------------------------

/**
 * Open the AI Study Tutor panel for the given session.
 * Loads conversation history and focuses the input.
 *
 * @param {string} sessionId — UUID of a complete analysis session.
 */
export function openTutor(sessionId) {
  _currentSessionId = sessionId;
  _clearMessages();
  _clearTutorError();
  _setSendingState(false);

  // Update the context header if the element exists
  const ctx = _el('tutor-session-id');
  if (ctx) ctx.textContent = sessionId;

  _showPanel('tutor-panel');
  _loadHistory(sessionId);

  const input = _el('tutor-input');
  if (input) {
    input.value = '';
    setTimeout(() => input.focus(), 100);
  }
}

// Make available globally for cross-module use (report.js, dashboard.js)
window.openTutor = openTutor;

// ---------------------------------------------------------------------------
// Initialisation
// ---------------------------------------------------------------------------

function _init() {
  _buildQuickPrompts();

  // Send button
  const sendBtn = _el('btn-tutor-send');
  if (sendBtn) {
    sendBtn.addEventListener('click', () => {
      if (!_currentSessionId) return;
      const input = _el('tutor-input');
      const text = input ? input.value : '';
      _sendMessage(_currentSessionId, text);
    });
  }

  // Enter to send, Shift+Enter for newline
  const input = _el('tutor-input');
  if (input) {
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (!_currentSessionId || _isSending) return;
        _sendMessage(_currentSessionId, input.value);
      }
    });
  }

  // Back button — return to report panel if possible, else dashboard
  const backBtn = _el('btn-tutor-back');
  if (backBtn) {
    backBtn.addEventListener('click', () => {
      // Prefer going back to the report panel; dashboard is fallback
      const reportPanel = _el('report-panel');
      if (reportPanel && !reportPanel.hidden) {
        _showPanel('report-panel');
      } else {
        _showPanel('dashboard-panel');
      }
    });
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _init);
} else {
  _init();
}
