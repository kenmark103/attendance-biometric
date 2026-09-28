import React, { useEffect, useState } from 'react';
import { colors } from '../theme.js';

const AUTH_BASE = import.meta.env.VITE_AUTH_URL || 'http://localhost:8002';

function parseToken(t) {
  try {
    const payload = JSON.parse(atob(t.split('.')[1]));
    return payload;
  } catch { return null; }
}

export default function AuthHeader() {
  const [user, setUser] = useState(() => {
    const t = localStorage.getItem('token');
    return t ? parseToken(t) : null;
  });
  const [providers, setProviders] = useState([]);

  useEffect(() => {
    // capture token from redirect ?token=...
    const url = new URL(window.location.href);
    const tok = url.searchParams.get('token');
    if (tok) {
      localStorage.setItem('token', tok);
      const p = parseToken(tok);
      setUser(p);
      url.searchParams.delete('token');
      window.history.replaceState({}, '', url.toString());
    }
  }, []);

  useEffect(() => {
    fetch(`${AUTH_BASE.replace(/\/$/, '')}/auth/providers`).then(r=>r.json()).then(d=>setProviders(d.configured||[])).catch(()=>setProviders([]));
  }, []);

  // validate token against backend (optional, checks exp)
  useEffect(() => {
    const t = localStorage.getItem('token');
    if (!t) return;
    fetch(`${AUTH_BASE.replace(/\/$/, '')}/auth/me`, { headers: { Authorization: `Bearer ${t}` } })
      .then(r => { if (!r.ok) throw new Error('invalid'); return r.json(); })
      .then(p => setUser(p))
      .catch(() => { localStorage.removeItem('token'); setUser(null); });
  }, []);

  function signOut() {
    localStorage.removeItem('token');
    setUser(null);
  }

  if (user && user.email) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <span style={{ fontSize: 13, color: colors.muted }}>
          <span style={{ color: colors.ink, fontWeight: 600 }}>{user.name || user.email}</span>
          <span style={{ marginLeft: 6, fontFamily: "'IBM Plex Mono', monospace", fontSize: 11 }}>{user.email}</span>
          <span style={{ marginLeft: 6, fontSize: 11, background: colors.slate, color: '#fff', borderRadius: 3, padding: '1px 5px' }}>{user.role}</span>
        </span>
        <button onClick={signOut} style={{ fontFamily: 'inherit', fontSize: 13, padding: '6px 12px', border: `1px solid ${colors.line}`, background: colors.panel, borderRadius: 4, cursor: 'pointer' }}>Sign out</button>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
      {providers.includes('google') && (
        <a href={`${AUTH_BASE.replace(/\/$/, '')}/auth/login/google`} style={{ fontFamily: 'inherit', fontSize: 13, padding: '7px 14px', background: '#fff', border: `1px solid ${colors.line}`, borderRadius: 4, textDecoration: 'none', color: colors.ink, fontWeight: 500 }}>Sign in with Google</a>
      )}
      {providers.includes('entra') && (
        <a href={`${AUTH_BASE.replace(/\/$/, '')}/auth/login/entra`} style={{ fontFamily: 'inherit', fontSize: 13, padding: '7px 14px', background: colors.slate, border: `1px solid ${colors.slate}`, borderRadius: 4, textDecoration: 'none', color: '#fff', fontWeight: 600 }}>Sign in with Microsoft</a>
      )}
      {providers.length === 0 && <span style={{ fontSize: 12, color: colors.muted }}>Auth not configured</span>}
    </div>
  );
}
