import React, { useEffect, useState } from 'react';
import logoUrl from '../assets/tbl-logo.svg';
import { colors, brand } from '../theme.js';

const AUTH_BASE = import.meta.env.VITE_AUTH_URL || 'http://localhost:8002';

export default function LoginPage() {
  const [providers, setProviders] = useState([]);

  useEffect(() => {
    fetch(`${AUTH_BASE.replace(/\/$/, '')}/auth/providers`)
      .then(r => r.json())
      .then(d => setProviders(d.configured || []))
      .catch(() => setProviders([]));
  }, []);

  const hasGoogle = providers.includes('google');
  const hasEntra = providers.includes('entra');
  // show both buttons for preview even if backend reports [] (dev with AUTH_REQUIRED=false)
  const showGoogle = true; // preview: always show; backend will 501 if not configured
  const showEntra = true;

  return (
    <div style={{ minHeight: '100vh', background: colors.paper, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24, fontFamily: "'IBM Plex Sans', sans-serif", boxSizing: 'border-box' }}>
      <div style={{ width: '100%', maxWidth: 440, background: colors.panel, border: `1px solid ${colors.line}`, borderRadius: 8, padding: '40px 36px', boxShadow: '0 4px 24px rgba(0,0,0,0.06)', textAlign: 'center' }}>
        <img src={logoUrl} alt="Technobrain" style={{ height: 52, width: 'auto', margin: '0 auto 20px', display: 'block' }} />
        <h1 style={{ fontFamily: "'Fraunces', Georgia, serif", fontSize: 22, fontWeight: 700, color: colors.slate, margin: '0 0 6px' }}>Attendance Dashboard</h1>
        <p style={{ fontSize: 13, color: colors.muted, margin: '0 0 28px', lineHeight: 1.5 }}>Sign in with your organization account to continue.</p>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <a
            href={`${AUTH_BASE.replace(/\/$/, '')}/auth/login/entra`}
            style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10, padding: '12px 16px', background: colors.slate, color: '#fff', border: `1px solid ${colors.slate}`, borderRadius: 6, textDecoration: 'none', fontWeight: 600, fontSize: 14, cursor: 'pointer' }}
          >
            <span style={{ width: 18, height: 18, background: '#fff', borderRadius: 2, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, color: brand.slate, fontWeight: 800 }}>M</span>
            Continue with Microsoft 365
          </a>
          <a
            href={`${AUTH_BASE.replace(/\/$/, '')}/auth/login/google`}
            style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10, padding: '12px 16px', background: '#fff', color: colors.ink, border: `1px solid ${colors.line}`, borderRadius: 6, textDecoration: 'none', fontWeight: 500, fontSize: 14, cursor: 'pointer' }}
          >
            <span style={{ width: 18, height: 18, borderRadius: '50%', background: '#fff', border: `1px solid ${colors.line}`, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, fontWeight: 700, color: '#4285F4' }}>G</span>
            Continue with Google
          </a>
        </div>

        <div style={{ marginTop: 18, fontSize: 11, color: colors.muted, lineHeight: 1.4 }}>
          {!hasEntra && <div style={{ color: brand.orange, marginBottom: 4 }}>M365 not yet configured — button will show 501 until ENTRA_* is set.</div>}
          {!hasGoogle && <div>Google is temporary for dev — clear GOOGLE_* in .env to hide it.</div>}
          {hasGoogle && hasEntra && <div>Both providers active. Remove Google via .env when done.</div>}
          <div style={{ marginTop: 8 }}>Route: <code>/login</code> — not enforced yet. Visit <a href="/" style={{ color: colors.slate }}>dashboard</a> without sign-in.</div>
        </div>

        <div style={{ marginTop: 24, paddingTop: 16, borderTop: `1px solid ${colors.line}`, fontSize: 11, color: colors.muted }}>
          Empowering Lives
        </div>
      </div>
    </div>
  );
}
