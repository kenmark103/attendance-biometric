import React, { useState } from 'react';
import logoUrl from '../assets/tbl-logo.svg';
import { colors } from '../theme.js';
import { changePassword as apiChangePassword } from '../api.js';
import { logout, setSession } from '../auth.js';

export default function ChangePasswordPage({ onChanged, onLogout }) {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const data = await apiChangePassword(current, next);
      setSession(data.access_token, data.user);
      onChanged(data.user);
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ minHeight: '100vh', background: colors.paper, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24, fontFamily: "'IBM Plex Sans', sans-serif", boxSizing: 'border-box' }}>
      <div style={{ width: '100%', maxWidth: 440, background: colors.panel, border: `1px solid ${colors.line}`, borderRadius: 8, padding: '40px 36px', textAlign: 'center' }}>
        <img src={logoUrl} alt="Technobrain" style={{ height: 52, width: 'auto', margin: '0 auto 20px', display: 'block' }} />
        <h1 style={{ fontSize: 20, fontWeight: 700, color: colors.slate, margin: '0 0 6px' }}>Set a new password</h1>
        <p style={{ fontSize: 13, color: colors.muted, margin: '0 0 24px' }}>Your account requires a password change before you can continue. Minimum 12 characters.</p>
        <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 10, textAlign: 'left' }}>
          <label style={{ fontSize: 12, color: colors.muted }}>Current password
            <input value={current} onChange={(e) => setCurrent(e.target.value)} type="password" autoComplete="current-password" required
              style={{ display: 'block', width: '100%', boxSizing: 'border-box', marginTop: 4, padding: '10px 12px', fontSize: 14, border: `1px solid ${colors.line}`, borderRadius: 6, fontFamily: 'inherit' }} />
          </label>
          <label style={{ fontSize: 12, color: colors.muted }}>New password (12+ characters)
            <input value={next} onChange={(e) => setNext(e.target.value)} type="password" autoComplete="new-password" required minLength={12}
              style={{ display: 'block', width: '100%', boxSizing: 'border-box', marginTop: 4, padding: '10px 12px', fontSize: 14, border: `1px solid ${colors.line}`, borderRadius: 6, fontFamily: 'inherit' }} />
          </label>
          {error && <div style={{ fontSize: 13, color: '#A63D2F' }}>{error}</div>}
          <button type="submit" disabled={busy} style={{ padding: '12px 16px', background: colors.slate, color: '#fff', border: `1px solid ${colors.slate}`, borderRadius: 6, fontWeight: 600, fontSize: 14, cursor: busy ? 'wait' : 'pointer', fontFamily: 'inherit' }}>
            {busy ? 'Saving…' : 'Change password'}
          </button>
        </form>
        <button onClick={async () => { await logout(); onLogout(); }} style={{ marginTop: 16, background: 'none', border: 'none', color: colors.slate, fontSize: 13, cursor: 'pointer', textDecoration: 'underline', fontFamily: 'inherit' }}>
          Sign out
        </button>
      </div>
    </div>
  );
}
