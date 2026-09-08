/**
 * auth.js — Authentication module for StudyLens AI
 *
 * Handles user registration, login, logout, and token storage.
 * Uses fetch() directly (api.js is not yet implemented).
 * JWT is stored exclusively in sessionStorage, never localStorage.
 *
 * Public API:
 *   register(email, password) — POST /auth/register
 *   login(email, password)    — POST /auth/login
 *   logout()                  — clear session and reset UI
 *   getToken()                — return current JWT or null
 */

// ---------------------------------------------------------------------------
// Token storage — sessionStorage only
// ---------------------------------------------------------------------------

const TOKEN_KEY = 'studylens_token';

/** Return the stored JWT, or null when not authenticated. */
export function getToken() {
  return sessionStorage.getItem(TOKEN_KEY);
}

function _setToken(token) {
  sessionStorage.setItem(TOKEN_KEY, token);
}

function _clearToken() {
  sessionStorage.removeItem(TOKEN_KEY);
}

// ---------------------------------------------------------------------------
// UI helpers — panel and nav visibility
// ---------------------------------------------------------------------------

/**
 * Show one panel and hide all others.
 * @param {string} panelId - The id of the panel to show.
 */
function _showPanel(panelId) {
  const panels = [
    'auth-panel',
    'upload-panel',
    'progress-panel',
    'report-panel',
    'history-panel',
    'tutor-panel',
    'dashboard-panel',
  ];
  panels.forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.hidden = id !== panelId;
  });
}

/** Switch navigation to the authenticated state. */
function _showAuthenticatedNav() {
  const authLinks = document.getElementById('nav-auth-links');
  const userLinks = document.getElementById('nav-user-links');
  if (authLinks) authLinks.hidden = true;
  if (userLinks) userLinks.hidden = false;
}

/** Switch navigation to the logged-out state. */
function _showUnauthenticatedNav() {
  const authLinks = document.getElementById('nav-auth-links');
  const userLinks = document.getElementById('nav-user-links');
  if (authLinks) authLinks.hidden = false;
  if (userLinks) userLinks.hidden = true;
}

/**
 * Display an error message in a container element.
 * @param {string} containerId - Element id of the error container.
 * @param {string} message     - Human-readable error text.
 */
function _showError(containerId, message) {
  const el = document.getElementById(containerId);
  if (!el) return;
  el.textContent = message;
  el.hidden = false;
}

/**
 * Clear and hide an error container.
 * @param {string} containerId - Element id of the error container.
 */
function _clearError(containerId) {
  const el = document.getElementById(containerId);
  if (!el) return;
  el.textContent = '';
  el.hidden = true;
}

/**
 * Display a success message in a container element.
 * @param {string} containerId - Element id of the status container.
 * @param {string} message     - Human-readable success text.
 */
function _showSuccess(containerId, message) {
  const el = document.getElementById(containerId);
  if (!el) return;
  el.textContent = message;
  el.hidden = false;
  el.classList.add('alert-success');
  el.classList.remove('alert-error');
}

// ---------------------------------------------------------------------------
// Auth tab switching (Login / Register)
// ---------------------------------------------------------------------------

function _activateTab(activeTabId, inactiveTabId, showFormId, hideFormId) {
  const activeTab = document.getElementById(activeTabId);
  const inactiveTab = document.getElementById(inactiveTabId);
  const showForm = document.getElementById(showFormId);
  const hideForm = document.getElementById(hideFormId);

  if (activeTab) {
    activeTab.setAttribute('aria-selected', 'true');
    activeTab.classList.add('auth-tab--active');
  }
  if (inactiveTab) {
    inactiveTab.setAttribute('aria-selected', 'false');
    inactiveTab.classList.remove('auth-tab--active');
  }
  if (showForm) showForm.hidden = false;
  if (hideForm) hideForm.hidden = true;
}

function _bindTabControls() {
  const tabLogin = document.getElementById('tab-login');
  const tabRegister = document.getElementById('tab-register');

  if (tabLogin) {
    tabLogin.addEventListener('click', () => {
      _activateTab('tab-login', 'tab-register', 'form-login', 'form-register');
      _clearError('login-error');
    });
  }

  if (tabRegister) {
    tabRegister.addEventListener('click', () => {
      _activateTab('tab-register', 'tab-login', 'form-register', 'form-login');
      _clearError('register-error');
    });
  }
}

// ---------------------------------------------------------------------------
// Nav button wiring
// ---------------------------------------------------------------------------

function _bindNavControls() {
  // "Log in" button in nav → show auth panel on login tab
  const navShowLogin = document.getElementById('nav-show-login');
  if (navShowLogin) {
    navShowLogin.addEventListener('click', () => {
      _showPanel('auth-panel');
      _activateTab('tab-login', 'tab-register', 'form-login', 'form-register');
    });
  }

  // "Register" button in nav → show auth panel on register tab
  const navShowRegister = document.getElementById('nav-show-register');
  if (navShowRegister) {
    navShowRegister.addEventListener('click', () => {
      _showPanel('auth-panel');
      _activateTab('tab-register', 'tab-login', 'form-register', 'form-login');
    });
  }

  // "Dashboard" button in nav → show dashboard panel
  const navShowDashboard = document.getElementById('nav-show-dashboard');
  if (navShowDashboard) {
    navShowDashboard.addEventListener('click', () => {
      _showPanel('dashboard-panel');
      if (window.loadDashboard) window.loadDashboard();
    });
  }

  // "Log out" button
  const navLogout = document.getElementById('nav-logout');
  if (navLogout) {
    navLogout.addEventListener('click', logout);
  }
}

// ---------------------------------------------------------------------------
// Public: register(email, password)
// ---------------------------------------------------------------------------

/**
 * Register a new account.
 *
 * Sends POST /auth/register with JSON body.
 * On success, switches the tab to the login form with a confirmation message.
 * On error, displays a human-readable message in the register error container.
 *
 * @param {string} email
 * @param {string} password
 */
export async function register(email, password) {
  _clearError('register-error');

  let response;
  try {
    response = await fetch('/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
  } catch (_networkErr) {
    _showError('register-error', 'Could not reach the server. Please check your connection.');
    return;
  }

  if (response.ok) {
    // Switch to login tab and show a confirmation
    _activateTab('tab-login', 'tab-register', 'form-login', 'form-register');
    _showSuccess('login-error', 'Account created — please log in.');
    // Clear the register form fields
    const emailEl = document.getElementById('register-email');
    const passEl = document.getElementById('register-password');
    if (emailEl) emailEl.value = '';
    if (passEl) passEl.value = '';
    return;
  }

  // Parse the error message from the backend
  let errorMessage = 'Registration failed. Please try again.';
  try {
    const data = await response.json();
    if (data && data.error) errorMessage = data.error;
  } catch (_) { /* ignore parse errors */ }

  _showError('register-error', errorMessage);
}

// ---------------------------------------------------------------------------
// Public: login(email, password)
// ---------------------------------------------------------------------------

/**
 * Authenticate an existing account.
 *
 * Sends POST /auth/login with JSON body.
 * On success, stores the JWT in sessionStorage, updates the nav, and shows
 * the upload panel.
 * On error, displays a human-readable message in the login error container.
 *
 * @param {string} email
 * @param {string} password
 * @returns {boolean} true on success, false on failure
 */
export async function login(email, password) {
  _clearError('login-error');

  let response;
  try {
    response = await fetch('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
  } catch (_networkErr) {
    _showError('login-error', 'Could not reach the server. Please check your connection.');
    return false;
  }

  if (response.ok) {
    let data;
    try {
      data = await response.json();
    } catch (_) {
      _showError('login-error', 'Unexpected response from the server.');
      return false;
    }

    // Store token — sessionStorage only, never localStorage
    _setToken(data.token);

    // Clear form fields — do not leave credentials in the DOM
    const emailEl = document.getElementById('login-email');
    const passEl = document.getElementById('login-password');
    if (emailEl) emailEl.value = '';
    if (passEl) passEl.value = '';

    // Update UI to authenticated state
    _showAuthenticatedNav();
    _showPanel('dashboard-panel');

    // Load the dashboard if dashboard.js has already initialised
    if (window.loadDashboard) {
      window.loadDashboard();
    }

    return true;
  }

  let errorMessage = 'Invalid credentials.';
  try {
    const data = await response.json();
    if (data && data.error) errorMessage = data.error;
  } catch (_) { /* ignore */ }

  _showError('login-error', errorMessage);
  return false;
}

// ---------------------------------------------------------------------------
// Public: logout()
// ---------------------------------------------------------------------------

/**
 * Log out the current user.
 *
 * Clears the JWT from sessionStorage, resets the UI to the logged-out state,
 * and hides all authenticated-only panels.
 */
export function logout() {
  _clearToken();
  _showUnauthenticatedNav();

  // Reset the login form to the default tab
  _activateTab('tab-login', 'tab-register', 'form-login', 'form-register');
  _clearError('login-error');
  _clearError('register-error');
  _clearError('auth-error');

  // Show the auth panel; hide all others
  _showPanel('auth-panel');
}

// ---------------------------------------------------------------------------
// Initialisation — runs when the module is first loaded
// ---------------------------------------------------------------------------

/**
 * Initialise auth.js: bind all auth-related UI controls.
 * Called automatically when this module is loaded as type="module".
 */
function _init() {
  _bindTabControls();
  _bindNavControls();

  // Wire login form submit
  const formLogin = document.getElementById('form-login');
  if (formLogin) {
    formLogin.addEventListener('submit', async (e) => {
      e.preventDefault();
      const email = document.getElementById('login-email')?.value.trim() ?? '';
      const password = document.getElementById('login-password')?.value ?? '';
      const btn = document.getElementById('btn-login');
      if (btn) btn.disabled = true;
      await login(email, password);
      if (btn) btn.disabled = false;
    });
  }

  // Wire register form submit
  const formRegister = document.getElementById('form-register');
  if (formRegister) {
    formRegister.addEventListener('submit', async (e) => {
      e.preventDefault();
      const email = document.getElementById('register-email')?.value.trim() ?? '';
      const password = document.getElementById('register-password')?.value ?? '';
      const btn = document.getElementById('btn-register');
      if (btn) btn.disabled = true;
      await register(email, password);
      if (btn) btn.disabled = false;
    });
  }

  // Restore authenticated state on page reload if token is present
  if (getToken()) {
    _showAuthenticatedNav();
    _showPanel('dashboard-panel');
    // Load the dashboard; dashboard.js may not be ready yet on first tick
    setTimeout(() => {
      if (window.loadDashboard) window.loadDashboard();
    }, 0);
  }
}

// Auto-initialise when the DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _init);
} else {
  _init();
}
