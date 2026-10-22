// Access tokens stay in memory; the opaque refresh token is httpOnly.
let accessToken = null;
let expiresAt = 0;
let refreshPromise = null;
let refreshTimer = null;
let currentUser = null;
const listeners = new Set();

export function getAccessToken() { return accessToken; }
export function getCurrentUser() { return currentUser; }
export function subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); }
function setUser(user) { currentUser = user; listeners.forEach((fn) => fn(user)); }

function scheduleRefresh() {
  clearTimeout(refreshTimer);
  if (!expiresAt) return;
  refreshTimer = setTimeout(() => { refreshSession(); }, Math.max(5000, expiresAt - Date.now() - 60000));
}

export function setSession(token, user, expiresIn = 0) {
  accessToken = token;
  expiresAt = Date.now() + Number(expiresIn || 0) * 1000;
  setUser(user);
  scheduleRefresh();
}

export function clearSession() {
  clearTimeout(refreshTimer); refreshTimer = null;
  accessToken = null; expiresAt = 0; setUser(null);
}

async function withRefreshLock(run) {
  if (navigator.locks?.request) return navigator.locks.request('att-refresh', run);
  return run();
}

export async function refreshSession() {
  if (!refreshPromise) {
    refreshPromise = withRefreshLock(async () => {
      // Another tab-local caller may have refreshed while waiting for the lock.
      if (accessToken && expiresAt - Date.now() > 60000) return currentUser;
      const res = await fetch('/api/auth/refresh', { method: 'POST', credentials: 'include' });
      if (!res.ok) { clearSession(); window.dispatchEvent(new CustomEvent('auth:logout', { detail: 'expired' })); return null; }
      const data = await res.json();
      setSession(data.access_token, data.user, data.expires_in);
      return data.user;
    }).finally(() => { refreshPromise = null; });
  }
  return refreshPromise;
}

export function bootSession() { return refreshSession(); }

export async function apiFetch(url, opts = {}, retried = false) {
  if (accessToken && expiresAt - Date.now() < 60000) await refreshSession();
  const headers = { ...(opts.headers || {}) };
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  const res = await fetch(url, { ...opts, headers, credentials: 'include' });
  if (res.status === 401 && !retried && await refreshSession()) return apiFetch(url, opts, true);
  return res;
}

export async function loginEmail(email, password) {
  const res = await fetch('/api/auth/login', { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password }) });
  if (!res.ok) throw new Error(res.status === 429 ? 'Too many attempts, try again later.' : 'Invalid email or password.');
  const data = await res.json(); setSession(data.access_token, data.user, data.expires_in); return data.user;
}

export async function logout(reason = 'signed_out') {
  try { await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' }); } catch { /* local logout still succeeds */ }
  clearSession();
  window.dispatchEvent(new CustomEvent('auth:logout', { detail: reason }));
}

if (typeof window !== 'undefined') {
  const checkExpiry = () => { if (accessToken && expiresAt - Date.now() < 60000) refreshSession(); };
  window.addEventListener('focus', checkExpiry);
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') checkExpiry(); });
  window.addEventListener('auth:logout', () => clearSession());
}
