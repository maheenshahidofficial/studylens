/**
 * api.js — Authenticated fetch wrapper for StudyLens AI
 *
 * Provides a single function, apiFetch, that:
 *   - Attaches the JWT Authorization header from sessionStorage via getToken()
 *   - Preserves any caller-supplied headers
 *   - Does NOT set Content-Type when the body is FormData (browser handles multipart boundary)
 *   - Returns parsed JSON on success
 *   - Throws an Error with a human-readable message on failure (never exposes
 *     raw HTTP status codes, stack traces, or exception class names to callers)
 *
 * Public API:
 *   apiFetch(method, path, body?) → Promise<any>
 *
 * Usage examples:
 *   const sessions = await apiFetch('GET', '/api/sessions');
 *   const result   = await apiFetch('POST', '/api/analyze', formData);
 *   const detail   = await apiFetch('GET', `/api/sessions/${id}`);
 */

import { getToken } from './auth.js';

/**
 * Perform an authenticated fetch request.
 *
 * @param {string}                        method  - HTTP method ('GET', 'POST', etc.)
 * @param {string}                        path    - Absolute path on the same origin, e.g. '/api/sessions'
 * @param {FormData|object|string|null}   [body]  - Optional request body.
 *   - Pass a FormData instance for multipart file uploads.
 *   - Pass a plain object or string for JSON payloads (caller must set
 *     Content-Type: application/json in extraHeaders if needed, or this
 *     function will set it automatically for plain objects).
 * @param {object}                        [extraHeaders={}] - Additional headers to merge.
 * @returns {Promise<any>} Parsed JSON response body.
 * @throws {Error} With a human-readable message when the response is not OK.
 */
export async function apiFetch(method, path, body = null, extraHeaders = {}) {
  const token = getToken();

  // Build headers — start with the auth header when a token is present
  const headers = {};

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  // Merge any extra headers supplied by the caller
  Object.assign(headers, extraHeaders);

  // Determine the fetch options
  const fetchOptions = {
    method: method.toUpperCase(),
    headers,
  };

  if (body !== null && body !== undefined) {
    if (body instanceof FormData) {
      // Do NOT set Content-Type — the browser must set the multipart boundary
      fetchOptions.body = body;
    } else if (typeof body === 'string') {
      fetchOptions.body = body;
      // Only set Content-Type if the caller hasn't already provided one
      if (!headers['Content-Type'] && !headers['content-type']) {
        headers['Content-Type'] = 'text/plain';
      }
    } else {
      // Plain object — serialise to JSON
      fetchOptions.body = JSON.stringify(body);
      if (!headers['Content-Type'] && !headers['content-type']) {
        headers['Content-Type'] = 'application/json';
      }
    }
  }

  // Perform the request
  let response;
  try {
    response = await fetch(path, fetchOptions);
  } catch (_networkErr) {
    // Network-level failure (offline, DNS, CORS preflight abort, etc.)
    throw new Error('Could not reach the server. Please check your connection and try again.');
  }

  // Successful response — parse and return JSON
  if (response.ok) {
    // Some endpoints may return 204 No Content
    const contentType = response.headers.get('Content-Type') ?? '';
    if (response.status === 204 || !contentType.includes('application/json')) {
      return null;
    }
    try {
      return await response.json();
    } catch (_parseErr) {
      throw new Error('The server returned an unexpected response.');
    }
  }

  // Error response — extract the human-readable message from the JSON body
  let errorMessage = 'Something went wrong. Please try again.';
  try {
    const contentType = response.headers.get('Content-Type') ?? '';
    if (contentType.includes('application/json')) {
      const data = await response.json();
      if (data && typeof data.error === 'string' && data.error.length > 0) {
        errorMessage = data.error;
      }
    }
  } catch (_) {
    // JSON parse failed — keep the generic message
  }

  // Throw with the human-readable message; do not include raw HTTP status
  throw new Error(errorMessage);
}
