// Reusable, token-aware API client for the FarmIQ frontend.
//
// The auth endpoints (/api/auth/login, /api/auth/register) return an
// access_token in the response body. App.jsx captures it via setAuthToken()
// so all subsequent protected requests send it as a Bearer token.
//
// The token is persisted to localStorage so it survives page reloads and
// Capacitor app restarts. Sensitive note: the service-role key is never
// stored here — this only stores the Supabase user access_token.
import { API_BASE_URL } from "@/config/api";

const TOKEN_KEY = "farmiq_access_token";
const USER_KEY = "farmiq_user";

// Initialise from storage on module load (survives app restart on Android)
let authToken = localStorage.getItem(TOKEN_KEY) || null;

export function setAuthToken(token) {
  authToken = token || null;
  if (authToken) localStorage.setItem(TOKEN_KEY, authToken);
  else localStorage.removeItem(TOKEN_KEY);
}

export function getAuthToken() {
  return authToken;
}

export function clearAuthToken() {
  authToken = null;
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

// ── User persistence ──────────────────────────────────────────────────────────
// Store the full user object so App.jsx can restore it on reload.
export function saveUser(user) {
  if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
  else localStorage.removeItem(USER_KEY);
}

export function loadUser() {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

/**
 * Low-level request wrapper. Throws an Error with `.status` and `.data` on
 * non-2xx responses (the message mirrors the backend `{"detail": ...}` shape
 * so existing toast handlers can keep reading `err.message`).
 */
export async function apiRequest(
  path,
  { method = "GET", body, rawBody, headers } = {},
) {
  const init = { method, headers: { ...(headers || {}) } };
  if (authToken) init.headers["Authorization"] = `Bearer ${authToken}`;
  if (rawBody !== undefined) {
    // FormData / Blob: let the browser set Content-Type (multipart boundary).
    init.body = rawBody;
  } else if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }

  const res = await fetch(`${API_BASE_URL}${path}`, init);
  let data = null;
  try {
    data = await res.json();
  } catch {
    // non-JSON response (e.g. 204 No Content)
  }

  if (!res.ok) {
    const err = new Error(data?.detail ?? `Request failed (${res.status})`);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

export const apiGet = (path, opts) => apiRequest(path, { ...opts });
export const apiPost = (path, body, opts) =>
  apiRequest(path, { method: "POST", body, ...opts });
export const apiUpload = (path, formData, opts) =>
  apiRequest(path, { method: "POST", rawBody: formData, ...opts });
export const apiPatch = (path, body, opts) =>
  apiRequest(path, { method: "PATCH", body, ...opts });
export const apiDelete = (path, opts) =>
  apiRequest(path, { method: "DELETE", ...opts });

/**
 * POST a JSON body and read a binary response as a Blob. Used by
 * /api/voice/speak, which returns MP3 audio rather than JSON. Error responses
 * are still JSON, so they are decoded to keep `err.message` / `err.status`
 * consistent with apiRequest().
 */
export async function apiPostBlob(path, body) {
  const headers = { "Content-Type": "application/json" };
  if (authToken) headers["Authorization"] = `Bearer ${authToken}`;

  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body ?? {}),
  });

  if (!res.ok) {
    let detail = null;
    try {
      detail = (await res.json())?.detail;
    } catch {
      // Non-JSON error body (e.g. a proxy error page).
    }
    const err = new Error(detail ?? `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return res.blob();
}
