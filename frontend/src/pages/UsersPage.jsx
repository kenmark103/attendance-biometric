import React, { useEffect, useState } from 'react';
import { colors } from '../theme.js';
import { fetchUsers, createUser, patchUser, resetUserPassword } from '../api.js';

const td = { padding: '10px 12px', borderBottom: `1px solid ${colors.line}`, fontSize: 13 };
const th = { ...td, textAlign: 'left', fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.4, color: colors.muted };
const btn = { fontFamily: 'inherit', fontSize: 12, padding: '6px 10px', border: `1px solid ${colors.line}`, background: '#fff', borderRadius: 4, cursor: 'pointer' };

export default function UsersPage() {
  const [users, setUsers] = useState(null);
  const [error, setError] = useState(null);
  const [form, setForm] = useState({ email: '', display_name: '', role: 'viewer', auth_provider: 'local' });
  const [tempPw, setTempPw] = useState(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      setUsers(await fetchUsers());
      setError(null);
    } catch (e) {
      setError(String(e.message || e));
    }
  }

  useEffect(() => { load(); }, []);

  async function create(e) {
    e.preventDefault();
    setBusy(true);
    setTempPw(null);
    try {
      const created = await createUser(form);
      if (created.temporary_password) setTempPw({ email: created.email, pw: created.temporary_password });
      setForm({ email: '', display_name: '', role: 'viewer', auth_provider: 'local' });
      await load();
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setBusy(false);
    }
  }

  async function toggleRole(u) {
    const order = ['viewer', 'manager', 'admin'];
    const next = order[(order.indexOf(u.role) + 1) % order.length];
    try {
      await patchUser(u.id, { role: next });
      await load();
    } catch (err) {
      setError(String(err.message || err));
    }
  }

  async function toggleActive(u) {
    try {
      await patchUser(u.id, { is_active: !u.is_active });
      await load();
    } catch (err) {
      setError(String(err.message || err));
    }
  }

  async function resetPw(u) {
    if (u.provider !== 'local') return;
    try {
      const r = await resetUserPassword(u.id);
      setTempPw({ email: u.email, pw: r.temporary_password });
      await load();
    } catch (err) {
      setError(String(err.message || err));
    }
  }

  if (!users) return <div style={{ padding: 40, color: colors.muted, fontFamily: 'sans-serif' }}>Loading users…</div>;

  return (
    <div style={{ maxWidth: 1120, margin: '0 auto', padding: '24px 28px', fontFamily: "'IBM Plex Sans', sans-serif" }}>
      <h2 style={{ color: colors.slate, margin: '0 0 4px' }}>Users</h2>
      <p style={{ fontSize: 13, color: colors.muted, margin: '0 0 20px' }}>
        System logins — distinct from employees (attendance subjects). Entra roles are overwritten on next SSO login when Entra supplies a role.
      </p>
      {error && <div style={{ fontSize: 13, color: '#A63D2F', marginBottom: 12 }}>{error}</div>}
      {tempPw && (
        <div style={{ background: '#EFF6EC', border: '1px solid #BFD8B8', borderRadius: 6, padding: '12px 14px', marginBottom: 16, fontSize: 13 }}>
          Temporary password for <strong>{tempPw.email}</strong>:{' '}
          <code style={{ fontSize: 15, userSelect: 'all' }}>{tempPw.pw}</code>
          <div style={{ fontSize: 12, color: colors.muted, marginTop: 4 }}>Shown once. Give it to the user directly.</div>
        </div>
      )}

      <form onSubmit={create} style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 20, alignItems: 'flex-end' }}>
        <label style={{ fontSize: 12, color: colors.muted }}>Email
          <input value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required type="email"
            style={{ display: 'block', padding: '8px 10px', fontSize: 13, border: `1px solid ${colors.line}`, borderRadius: 4, fontFamily: 'inherit', minWidth: 220 }} />
        </label>
        <label style={{ fontSize: 12, color: colors.muted }}>Name
          <input value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })}
            style={{ display: 'block', padding: '8px 10px', fontSize: 13, border: `1px solid ${colors.line}`, borderRadius: 4, fontFamily: 'inherit' }} />
        </label>
        <label style={{ fontSize: 12, color: colors.muted }}>Role
          <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}
            style={{ display: 'block', padding: '8px 10px', fontSize: 13, border: `1px solid ${colors.line}`, borderRadius: 4, fontFamily: 'inherit' }}>
            <option value="viewer">viewer</option>
            <option value="manager">manager</option>
            <option value="admin">admin</option>
          </select>
        </label>
        <label style={{ fontSize: 12, color: colors.muted }}>Provider
          <select value={form.auth_provider} onChange={(e) => setForm({ ...form, auth_provider: e.target.value })}
            style={{ display: 'block', padding: '8px 10px', fontSize: 13, border: `1px solid ${colors.line}`, borderRadius: 4, fontFamily: 'inherit' }}>
            <option value="local">local (email + password)</option>
            <option value="entra">entra (SSO, binds on first login)</option>
          </select>
        </label>
        <button type="submit" disabled={busy} style={{ ...btn, padding: '9px 16px', background: colors.slate, color: '#fff', border: `1px solid ${colors.slate}`, fontWeight: 600 }}>
          {busy ? 'Creating…' : 'Create user'}
        </button>
      </form>

      <table style={{ width: '100%', borderCollapse: 'collapse', background: colors.panel }}>
        <thead>
          <tr><th style={th}>Email</th><th style={th}>Name</th><th style={th}>Role</th><th style={th}>Provider</th><th style={th}>Active</th><th style={th}>Actions</th></tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id} style={{ opacity: u.is_active ? 1 : 0.55 }}>
              <td style={td}>{u.email}</td>
              <td style={td}>{u.display_name || '—'}</td>
              <td style={td}><button onClick={() => toggleRole(u)} style={btn} title="Click to cycle role">{u.role} ↻</button></td>
              <td style={td}>{u.provider}{u.must_change_password && u.provider === 'local' ? ' (must change pw)' : ''}</td>
              <td style={td}><button onClick={() => toggleActive(u)} style={btn}>{u.is_active ? 'yes' : 'no'} ↻</button></td>
              <td style={td}>{u.provider === 'local' && <button onClick={() => resetPw(u)} style={btn}>Reset password</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
