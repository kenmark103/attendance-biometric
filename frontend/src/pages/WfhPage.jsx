import React, { useEffect, useState } from 'react';
import { approveWfhPolicy, createWfhPolicy, fetchWfhPolicies, fetchWfhRecalls, revokeWfhPolicy } from '../api.js';
import { colors } from '../theme.js';

export default function WfhPage() {
  const [policies, setPolicies] = useState([]); const [recalls, setRecalls] = useState([]); const [error, setError] = useState('');
  const [form, setForm] = useState({ employee_id: '', type: 'default', start_date: '', end_date: '', note: '' });
  const load = () => Promise.all([fetchWfhPolicies(), fetchWfhRecalls()]).then(([p, r]) => { setPolicies(p); setRecalls(r); }).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);
  async function create(e) { e.preventDefault(); setError(''); try { await createWfhPolicy({ ...form, end_date: form.end_date || null }); setForm({ employee_id: '', type: 'default', start_date: '', end_date: '', note: '' }); load(); } catch (err) { setError(err.message); } }
  const button = { padding: '6px 9px', border: `1px solid ${colors.line}`, borderRadius: 4, background: '#fff', cursor: 'pointer' };
  return <main className="app-page-container" style={{ paddingTop: 28, paddingBottom: 28, fontFamily: "'IBM Plex Sans', sans-serif" }}>
    <h1 style={{ margin: 0, color: colors.slate, fontSize: 26 }}>Work from home</h1><p style={{ color: colors.muted, fontSize: 13 }}>Approved policies can be excluded from attendance metrics only when the feature flag is enabled.</p>
    {error && <p role="alert" style={{ color: colors.alert }}>{error}</p>}
    <form onSubmit={create} style={{ display: 'flex', gap: 8, flexWrap: 'wrap', margin: '18px 0' }}>
      <input required placeholder="Employee ID" value={form.employee_id} onChange={(e) => setForm({ ...form, employee_id: e.target.value })} />
      <select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}><option value="default">Default</option><option value="temporary">Temporary</option></select>
      <input required type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} />
      <input type="date" value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} />
      <input placeholder="Note" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} />
      <button style={button}>Add policy</button>
    </form>
    <div style={{ overflowX: 'auto' }}><table style={{ width: '100%', borderCollapse: 'collapse', background: colors.panel }}><thead><tr>{['Employee', 'Type', 'Dates', 'Status', 'Note', 'Actions'].map((h) => <th key={h} style={{ textAlign: 'left', padding: 9 }}>{h}</th>)}</tr></thead><tbody>{policies.map((p) => <tr key={p.id}><td style={{ padding: 9 }}>{p.employee_name || p.employee_id}</td><td>{p.type}</td><td>{p.start_date} – {p.end_date || 'ongoing'}</td><td>{p.status}</td><td>{p.note || '—'}</td><td>{p.status === 'pending' && <button style={button} onClick={() => approveWfhPolicy(p.id).then(load).catch((e) => setError(e.message))}>Approve</button>} {p.status !== 'revoked' && <button style={button} onClick={() => revokeWfhPolicy(p.id).then(load).catch((e) => setError(e.message))}>Revoke</button>}</td></tr>)}</tbody></table></div>
    <h3>Recalls</h3><p style={{ color: colors.muted, fontSize: 13 }}>{recalls.length ? `${recalls.length} recall(s) recorded.` : 'No recalls recorded.'}</p>
  </main>;
}
