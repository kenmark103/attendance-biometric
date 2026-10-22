import React, { useEffect, useState } from 'react';
import { fetchAuditLog, fetchAuthEvents } from '../api.js';
import { colors } from '../theme.js';

const cell = { padding: '9px 10px', borderBottom: `1px solid ${colors.line}`, fontSize: 12, verticalAlign: 'top' };

export default function AdminAuditPage({ kind }) {
  const [rows, setRows] = useState([]); const [error, setError] = useState('');
  useEffect(() => {
    const load = kind === 'events' ? fetchAuthEvents(200) : fetchAuditLog({ limit: 200 });
    load.then((data) => setRows(data.items || [])).catch((e) => setError(e.message));
  }, [kind]);
  const events = kind === 'events';
  return <main className="app-page-container" style={{ paddingTop: 28, paddingBottom: 28, fontFamily: "'IBM Plex Sans', sans-serif" }}>
    <h1 style={{ margin: '0 0 6px', color: colors.slate, fontSize: 26 }}>{events ? 'Authentication events' : 'Audit log'}</h1>
    <p style={{ color: colors.muted, fontSize: 13 }}>{events ? 'Sign-in and session activity. Tokens and passwords are never recorded.' : 'Administrative actions and metadata only.'}</p>
    {error && <p role="alert" style={{ color: colors.alert }}>{error}</p>}
    <div style={{ overflowX: 'auto', background: colors.panel, border: `1px solid ${colors.line}`, borderRadius: 6 }}>
      <table style={{ borderCollapse: 'collapse', width: '100%' }}><thead><tr>
        {(events ? ['Time', 'Event', 'Method', 'Email', 'Detail', 'IP'] : ['Time', 'Actor', 'Action', 'Entity', 'Before', 'After']).map((h) => <th key={h} style={{ ...cell, textAlign: 'left', color: colors.muted }}>{h}</th>)}
      </tr></thead><tbody>{rows.map((row) => events ? <tr key={row.id}><td style={cell}>{row.ts}</td><td style={cell}>{row.event}</td><td style={cell}>{row.method || '—'}</td><td style={cell}>{row.email || '—'}</td><td style={cell}>{row.detail || '—'}</td><td style={cell}>{row.ip || '—'}</td></tr> : <tr key={row.id}><td style={cell}>{row.ts}</td><td style={cell}>{row.actor_email || 'System'}</td><td style={cell}>{row.action}</td><td style={cell}>{row.entity_type}:{row.entity_id}</td><td style={cell}><code>{row.before ? JSON.stringify(row.before) : '—'}</code></td><td style={cell}><code>{row.after ? JSON.stringify(row.after) : '—'}</code></td></tr>)}</tbody></table>
    </div>
  </main>;
}
