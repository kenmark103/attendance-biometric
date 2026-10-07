import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { colors } from '../theme.js';
import { getCurrentUser, logout, subscribe } from '../auth.js';

export default function AuthHeader({ user: propUser, onLogout }) {
  const [liveUser, setLiveUser] = useState(() => getCurrentUser());
  useEffect(() => subscribe(setLiveUser), []);
  const u = propUser || liveUser;
  const navigate = useNavigate();

  async function signOut() {
    await logout();
    if (onLogout) onLogout();
    navigate('/login', { replace: true });
  }

  if (u && u.email) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <span style={{ fontSize: 13, color: colors.muted }}>
          <span style={{ color: colors.ink, fontWeight: 600 }}>{u.display_name || u.email}</span>
          <span style={{ marginLeft: 6, fontFamily: "'IBM Plex Mono', monospace", fontSize: 11 }}>{u.email}</span>
          <span style={{ marginLeft: 6, fontSize: 11, background: colors.slate, color: '#fff', borderRadius: 3, padding: '1px 5px' }}>{u.role}</span>
        </span>
        {u.role === 'admin' && (
          <Link to="/users" style={{ fontSize: 13, color: colors.slate }}>Users</Link>
        )}
        <Link to="/" style={{ fontSize: 13, color: colors.slate }}>Dashboard</Link>
        <button onClick={signOut} style={{ fontFamily: 'inherit', fontSize: 13, padding: '6px 12px', border: `1px solid ${colors.line}`, background: colors.panel, borderRadius: 4, cursor: 'pointer' }}>Sign out</button>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
      <Link to="/login" style={{ fontFamily: 'inherit', fontSize: 13, padding: '7px 14px', background: colors.slate, border: `1px solid ${colors.slate}`, borderRadius: 4, textDecoration: 'none', color: '#fff', fontWeight: 600 }}>Sign in</Link>
    </div>
  );
}
