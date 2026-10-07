// Auth state: access token lives in memory only (never localStorage).
// Refresh token is an httpOnly cookie the browser sends automatically.
let accessToken = null;
let refreshPromise = null;
let currentUser = null;
const listeners = new Set();

export function getAccessToken() { return accessToken; }
export function getCurrentUser() { return currentUser; }
export function subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); }
function setUser(u) { currentUser = u; listeners.forEach((fn) => fn(u)); }

export function setSession(token, user) {
  accessToken = token;
  setUser(user);
}

export function clearSession() {
  accessToken = null;
  setUser(null);
}

async function refreshSession() {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      let res = await fetch('/api/auth/refresh', { method: 'POST', credentials: 'include' });
      if (res.status === 401) {
        // another tab may have just rotated the cookie; retry once
        await new Promise((r) => setTimeout(r, 400));
        res = await fetch('/api/auth/refresh', { method: 'POST', credentials: 'include' });
      }
      if (!res.ok) { clearSession(); return null; }
      const data = await res.json();
      setSession(data.access_token, data.user);
      return data.user;
    })().finally(() => { refreshPromise = null; });
  }
  return refreshPromise;
}

export async function bootSession() {
  return refreshSession();
}

export async function apiFetch(url, opts = {}, retried = false) {
  const headers = { ...(opts.headers || {}) };
  if (accessToken) headers.Authorization = 'Bearer ' + accessToken;
  const res = await fetch(url, { ...opts, headers, credentials: 'include' });
  if (res.status === 401 && !retried) {
    const user = await refreshSession();
    if (user) return apiFetch(url, opts, true);
    window.dispatchEvent(new Event('auth:logout'));
  }
  return res;
}

export async function loginEmail(email, password) {
  const res = await fetch('/api/auth/login', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(res.status === 429 ? 'Too many attempts, try again later.' : 'Invalid email or password.' + (detail ? '' : ''));
  }
  const data = await res.json();
  setSession(data.access_token, data.user);
  return data.user;
}

export async function logout() {
  try {
    await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' });
  } catch { /* idempotent — still clear local state */ }
  clearSession();
}

if (typeof window !== 'undefined') {
  window.addEventListener('auth:logout', () => clearSession());
}
