import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import logoUrl from '../assets/tbl-logo.svg';
import { colors, brand } from '../theme.js';
import { loginEmail } from '../auth.js';

const ERROR_TEXT = {
  no_access: 'Your Microsoft account signed in, but no recognised role is assigned. Ask an administrator to grant Viewer or Admin access.',
  local_account_exists: 'This email already has a password account. Sign in with email instead — accounts are never merged automatically.',
  account_disabled: 'This account is disabled. Contact an administrator.',
  login_failed: 'Microsoft sign-in failed. Please try again.',
  inactive: 'This account is disabled. Contact an administrator.',
};

export default function LoginPage({ onLogin }) {
  const [config, setConfig] = useState(null);
  const [mode, setMode] = useState('email');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [ssoNote, setSsoNote] = useState(null);
  const navigate = useNavigate();

  useEffect(() => {
    const url = new URL(window.location.href);
    const code = url.searchParams.get('error');
    if (code) {
      setSsoNote(ERROR_TEXT[code] || ERROR_TEXT.login_failed);
      url.searchParams.delete('auth_error');
      window.history.replaceState({}, '', url.toString());
    }
    fetch('/api/auth/config').then((r) => r.ok ? r.json() : null).then((c) => {
      setConfig(c || { entra_enabled: false, local_auth_enabled: true });
      if (c?.entra_enabled && !c?.local_auth_enabled) setMode('sso');
    }).catch(() => setConfig({ entra_enabled: false, local_auth_enabled: true }));
  }, []);

  async function submitEmail(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const user = await loginEmail(email, password);
      onLogin(user);
      navigate('/', { replace: true });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ minHeight: '100vh', background: colors.paper, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24, fontFamily: "'IBM Plex Sans', sans-serif", boxSizing: 'border-box' }}>
      <div style={{ width: '100%', maxWidth: 440, background: colors.panel, border: `1px solid ${colors.line}`, borderRadius: 8, padding: '40px 36px', boxShadow: '0 4px 24px rgba(0,0,0,0.06)', textAlign: 'center' }}>
        <img src={logoUrl} alt="Technobrain" style={{ height: 52, width: 'auto', margin: '0 auto 20px', display: 'block' }} />
        <h1 style={{ fontFamily: "'Fraunces', Georgia, serif", fontSize: 22, fontWeight: 700, color: colors.slate, margin: '0 0 6px' }}>Attendance Dashboard</h1>
        <p style={{ fontSize: 13, color: colors.muted, margin: '0 0 28px', lineHeight: 1.5 }}>Sign in with your organization account to continue.</p>

        {ssoNote && <div style={{ fontSize: 13, color: brand.orange, background: '#FDF3E7', border: '1px solid #F0D9B5', borderRadius: 6, padding: '10px 12px', marginBottom: 16, textAlign: 'left' }}>{ssoNote}</div>}

        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {config?.entra_enabled && <button
            onClick={() => { window.location = '/api/auth/entra/login'; }}
            style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10, padding: '12px 16px', background: colors.slate, color: '#fff', border: `1px solid ${colors.slate}`, borderRadius: 6, fontWeight: 600, fontSize: 14, cursor: 'pointer', fontFamily: 'inherit' }}
          >
            <span style={{ width: 18, height: 18, background: '#fff', borderRadius: 2, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, color: brand.slate, fontWeight: 800 }}>M</span>
            Sign in with Microsoft
          </button>}

          {config?.local_auth_enabled && mode === 'sso' ? (
            <button onClick={() => setMode('email')} style={{ background: 'none', border: 'none', color: colors.slate, fontSize: 13, cursor: 'pointer', textDecoration: 'underline', fontFamily: 'inherit' }}>
              Sign in with email instead
            </button>
          ) : config?.local_auth_enabled ? (
            <form onSubmit={submitEmail} style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 4, textAlign: 'left' }}>
              <label style={{ fontSize: 12, color: colors.muted }}>Work email
                <input value={email} onChange={(e) => setEmail(e.target.value)} type="email" autoComplete="username" required
                  style={{ display: 'block', width: '100%', boxSizing: 'border-box', marginTop: 4, padding: '10px 12px', fontSize: 14, border: `1px solid ${colors.line}`, borderRadius: 6, fontFamily: 'inherit' }} />
              </label>
              <label style={{ fontSize: 12, color: colors.muted }}>Password
                <input value={password} onChange={(e) => setPassword(e.target.value)} type="password" autoComplete="current-password" required
                  style={{ display: 'block', width: '100%', boxSizing: 'border-box', marginTop: 4, padding: '10px 12px', fontSize: 14, border: `1px solid ${colors.line}`, borderRadius: 6, fontFamily: 'inherit' }} />
              </label>
              {error && <div style={{ fontSize: 13, color: '#A63D2F' }}>{error}</div>}
              <button type="submit" disabled={busy} style={{ padding: '12px 16px', background: '#fff', color: colors.ink, border: `1px solid ${colors.line}`, borderRadius: 6, fontWeight: 600, fontSize: 14, cursor: busy ? 'wait' : 'pointer', fontFamily: 'inherit' }}>
                {busy ? 'Signing in…' : 'Sign in with email'}
              </button>
              {config?.entra_enabled && <button type="button" onClick={() => setMode('sso')} style={{ background: 'none', border: 'none', color: colors.slate, fontSize: 13, cursor: 'pointer', textDecoration: 'underline', fontFamily: 'inherit' }}>
                Back to Microsoft sign-in
              </button>}
            </form>
          ) : null}
        </div>

        <div style={{ marginTop: 24, paddingTop: 16, borderTop: `1px solid ${colors.line}`, fontSize: 11, color: colors.muted }}>
          {config?.support_contact_text || ''}
        </div>
      </div>
    </div>
  );
}
