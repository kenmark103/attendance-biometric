// Leave data (#/leave, admin only): manual Zoho report upload, preview,
// commit, history, leave-type admin. Inline styles match the other views.
import React, { useState, useEffect, useMemo } from 'react';
import { colors } from '../theme.js';
import {
  uploadLeave, fetchLeaveImport, fetchLeaveIssues, fetchLeaveChanges,
  commitLeaveImport, discardLeaveImport, revertLeaveImport,
  fetchLeaveImportHistory, fetchLeaveTypes, putLeaveType,
  reprocessLeave, downloadLeaveSample,
} from '../api.js';

const th = { textAlign: 'left', padding: '10px 16px', color: colors.muted, fontWeight: 500, fontSize: 12 };
const td = { padding: '9px 16px', fontSize: 13 };
const card = { background: colors.panel, border: `1px solid ${colors.line}`, borderRadius: 4, padding: 16, marginBottom: 24 };
const btn = {
  fontFamily: 'inherit', fontSize: 13, padding: '8px 16px', cursor: 'pointer',
  border: `1px solid ${colors.line}`, borderRadius: 4, background: colors.paper, color: colors.ink,
};
const primaryBtn = { ...btn, background: colors.select, borderColor: colors.select, color: '#fff' };
const dangerBtn = { ...btn, color: colors.alert, borderColor: colors.alert };

function httpMessage(status) {
  if (status === 401 || status === 403) return 'Please sign in again, then retry.';
  if (status === 409) return 'Something changed while you worked — re-run the preview or wait, then retry.';
  if (status === 413) return 'File too large (max 10 MB).';
  if (status === 415) return 'Wrong file type — expected .xls or .xlsx.';
  if (status === 422) return 'The file could not be read as a leave report.';
  if (status >= 500) return 'The request failed and nothing was saved — try again.';
  return 'Request failed — check the connection and retry.';
}

function errText(e) {
  const m = /\/leave\/\S+ (\d+):?/.exec(String(e.message || ''));
  const status = m ? Number(m[1]) : 0;
  const detail = String(e.message || '').split(':').slice(1).join(':').trim();
  return `${httpMessage(status)}${detail ? ` (${detail.slice(0, 160)})` : ''}`;
}

function uid() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
  return `key-${Date.now()}-${Math.floor(Math.random() * 1e9)}`;
}

function CoverageBanner({ coverage }) {
  const through = coverage?.leave_coverage?.through_date || null;
  const stale = through && (Date.now() - new Date(through + 'T00:00:00Z').getTime()) / 86400000 > 10;
  return (
    <div style={{
      border: `1px solid ${stale ? '#c58a1b' : colors.line}`, background: stale ? '#fbf3dc' : colors.panel,
      borderRadius: 4, padding: '9px 14px', fontSize: 13, marginBottom: 16, color: colors.ink,
    }}>
      {through
        ? <>Leave data current through <strong>{through}</strong>
          {stale && <> — older than 10 days. HR sends the report weekly; please upload the latest file.</>}</>
        : <>No leave data loaded yet. Absences are shown as &ldquo;No record&rdquo; and are not reconciled with approved leave.</>}
    </div>
  );
}

function UploadPanel({ onUploaded, busy, setBusy, setError }) {
  const [drag, setDrag] = useState(false);
  async function send(file) {
    if (!file) return;
    if (!/\.xlsx?$/i.test(file.name)) { setError('Wrong file type — expected .xls or .xlsx.'); return; }
    if (file.size > 10 * 1024 * 1024) { setError('File too large (max 10 MB).'); return; }
    setBusy(true);
    setError(null);
    try {
      onUploaded(await uploadLeave(file));
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section style={card}>
      <h3 style={{ fontSize: 15, fontWeight: 600, margin: '0 0 8px' }}>Upload HR leave report</h3>
      <p style={{ fontSize: 12.5, color: colors.muted, margin: '0 0 12px' }}>
        One workbook, one sheet per month: header row with <code>Employee Id</code>, day columns
        labelled <code>1 - Jan</code>, <code>2 - Jan</code>, … HR re-sends the whole year each week;
        overlap is merged, never replaced. Max 10 MB.
        {' '}<button type="button" style={{ ...btn, padding: '4px 10px', fontSize: 12 }} onClick={() => downloadLeaveSample().catch((e) => setError(errText(e)))}>Download sample layout</button>
      </p>
      <div
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); send(e.dataTransfer.files[0]); }}
        style={{
          border: `2px dashed ${drag ? colors.select : colors.line}`, borderRadius: 4,
          padding: '28px 16px', textAlign: 'center', color: colors.muted, fontSize: 13.5,
          background: drag ? '#eef3fa' : 'transparent',
        }}>
        {busy ? 'Uploading and parsing…' : 'Drag and drop the .xls / .xlsx here, or '}
        {!busy && <label style={{ color: colors.select, cursor: 'pointer', fontWeight: 600 }}>
          choose a file
          <input type="file" accept=".xls,.xlsx" style={{ display: 'none' }}
            onChange={(e) => { send(e.target.files[0]); e.target.value = ''; }} />
        </label>}
      </div>
    </section>
  );
}

function SheetTable({ sheets, selected, setSelected }) {
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
      <thead><tr>
        <th style={th}>Include</th><th style={th}>Sheet</th><th style={th}>Period</th>
        <th style={{ ...th, textAlign: 'right' }}>Employees</th>
        <th style={{ ...th, textAlign: 'right' }}>Days</th><th style={th}>Status</th>
      </tr></thead>
      <tbody>
        {(sheets || []).map((s) => (
          <tr key={s.sheet} style={{ borderTop: `1px solid ${colors.line}` }}>
            <td style={td}>
              <input type="checkbox" disabled={s.blocked}
                checked={!s.blocked && selected.includes(s.sheet)}
                onChange={(e) => setSelected(e.target.checked
                  ? [...selected, s.sheet]
                  : selected.filter((x) => x !== s.sheet))} />
            </td>
            <td style={td}>{s.sheet}</td>
            <td style={td}>{s.start} – {s.end}</td>
            <td style={{ ...td, textAlign: 'right' }}>{s.employees}</td>
            <td style={{ ...td, textAlign: 'right' }}>{s.rows}</td>
            <td style={td}>{s.blocked
              ? <span style={{ color: colors.alert }}>Blocked — {s.reason || 'see issues'}</span>
              : <span style={{ color: colors.good }}>Ready</span>}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function IssuesTab({ importId }) {
  const [severity, setSeverity] = useState('');
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let dead = false;
    setData(null);
    fetchLeaveIssues(importId, severity ? { severity, limit: 500 } : { limit: 500 })
      .then((d) => { if (!dead) setData(d); })
      .catch((e) => { if (!dead) setError(errText(e)); });
    return () => { dead = true; };
  }, [importId, severity]);
  function downloadCSV() {
    if (!data) return;
    const esc = (v) => (/[",\n]/.test(String(v ?? '')) ? `"${String(v).replace(/"/g, '""')}"` : String(v ?? ''));
    const head = ['severity', 'code', 'sheet', 'occurrences', 'message'];
    const lines = data.issues.map((i) => [i.severity, i.code, i.sheet, i.occurrences, i.message]);
    const csv = '﻿' + [head, ...lines].map((r) => r.map(esc).join(',')).join('\n');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    a.download = `leave-issues-${importId}.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  }
  if (error) return <div style={{ color: colors.alert, fontSize: 13 }}>{error}</div>;
  if (!data) return <div style={{ color: colors.muted, fontSize: 13 }}>Loading issues…</div>;
  // Issues arrive aggregated server-side (one row per code/sheet).
  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, alignItems: 'center' }}>
        <select value={severity} onChange={(e) => setSeverity(e.target.value)} style={{ fontFamily: 'inherit', fontSize: 13, padding: '6px 10px' }}>
          <option value="">All severities ({data.total})</option>
          <option value="error">Errors</option>
          <option value="warning">Warnings</option>
          <option value="info">Info</option>
        </select>
        <button type="button" style={btn} onClick={downloadCSV}>Download CSV</button>
      </div>
      {data.issues.length === 0 && <div style={{ color: colors.muted, fontSize: 13 }}>No issues — clean file.</div>}
      {data.issues.map((i) => (
        <details key={i.id} style={{ border: `1px solid ${colors.line}`, borderRadius: 4, padding: '8px 12px', marginBottom: 8, fontSize: 13 }}>
          <summary style={{ cursor: 'pointer' }}>
            <strong style={{ color: i.severity === 'error' ? colors.alert : i.severity === 'warning' ? '#c58a1b' : colors.muted }}>
              [{i.severity}] {i.code}</strong>
            {' '}× {i.occurrences}{i.sheet ? ` · ${i.sheet}` : ''} — {i.message}
          </summary>
          {(i.samples || []).length > 0 && (
            <pre style={{ fontSize: 12, color: colors.muted, marginTop: 8 }}>
              {JSON.stringify(i.samples.slice(0, 5), null, 1)}
            </pre>
          )}
        </details>
      ))}
    </div>
  );
}

function ChangesTab({ importId, presentLikeOnly }) {
  const [type, setType] = useState(presentLikeOnly ? '' : 'changed');
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let dead = false;
    setData(null);
    fetchLeaveChanges(importId, { ...(type ? { type } : {}), limit: 200 })
      .then((d) => { if (!dead) setData(d); })
      .catch((e) => { if (!dead) setError(errText(e)); });
    return () => { dead = true; };
  }, [importId, type]);
  if (error) return <div style={{ color: colors.alert, fontSize: 13 }}>{error}</div>;
  if (!data) return <div style={{ color: colors.muted, fontSize: 13 }}>Loading changes…</div>;
  let rows = data.changes;
  if (presentLikeOnly) {
    rows = rows.filter((c) => /\/(0\.5)?P$/.test(c.new_raw) || /^0\.5/.test(c.new_raw));
  }
  return (
    <div>
      {!presentLikeOnly && (
        <div style={{ marginBottom: 12 }}>
          <select value={type} onChange={(e) => setType(e.target.value)} style={{ fontFamily: 'inherit', fontSize: 13, padding: '6px 10px' }}>
            <option value="changed">Changed</option>
            <option value="new">New</option>
            <option value="leave_removed">Leave removed</option>
            <option value="">All</option>
          </select>
          <span style={{ fontSize: 12, color: colors.muted, marginLeft: 8 }}>
            {data.total} total{data.total > rows.length ? `, showing ${rows.length}` : ''}
          </span>
        </div>
      )}
      {presentLikeOnly && (
        <p style={{ fontSize: 12.5, color: colors.muted }}>
          Leave days with a recorded presence (new or changed in this import).
          Past leave days that became non-leave are highlighted in Changes.
        </p>
      )}
      {rows.length === 0 && <div style={{ color: colors.muted, fontSize: 13 }}>Nothing here.</div>}
      {rows.length > 0 && (
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead><tr>
            <th style={th}>Employee</th><th style={th}>Date</th>
            <th style={th}>Old</th><th style={th}>New</th><th style={th}>Type</th>
          </tr></thead>
          <tbody>
            {rows.slice(0, 200).map((c, n) => (
              <tr key={n} style={{
                borderTop: `1px solid ${colors.line}`,
                background: c.change_type === 'leave_removed' ? '#f9e8e4' : 'transparent',
              }}>
                <td style={{ ...td, fontFamily: "'IBM Plex Mono', monospace" }}>{c.employee_id}</td>
                <td style={td}>{c.date}</td>
                <td style={td}>{c.old_raw ?? '—'}</td>
                <td style={td}><strong>{c.new_raw}</strong></td>
                <td style={td}>{c.change_type}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function UnmatchedTab({ preview }) {
  const names = preview?.preview_names || {};
  const [issues, setIssues] = useState([]);
  useEffect(() => {
    let dead = false;
    fetchLeaveIssues(preview.import_id, { limit: 1000 })
      .then((d) => { if (!dead) setIssues(d.issues); })
      .catch(() => {});
    return () => { dead = true; };
  }, [preview.import_id]);
  const missing = issues.find((i) => i.code === 'EMPLOYEE_NOT_IN_SYSTEM');
  const mismatched = issues.find((i) => i.code === 'EMPLOYEE_NAME_MISMATCH');
  const ids = [...new Set([
    ...((missing?.samples || []).map((s) => s.employee_id).filter(Boolean)),
    ...((mismatched?.samples || []).map((s) => s.employee_id).filter(Boolean)),
  ])];
  if (!missing && !mismatched) {
    return <div style={{ color: colors.muted, fontSize: 13 }}>Every ID in this file matches the employee directory.</div>;
  }
  return (
    <div style={{ fontSize: 13 }}>
      <p style={{ color: colors.muted }}>
        These IDs{missing ? ' are not in the directory (rows are stored and apply when they appear)' : ''}
        {mismatched ? ' or have a different directory name (possible mistyped ID)' : ''}.
        File names are shown here only and are never stored.
      </p>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead><tr><th style={th}>Employee ID</th><th style={th}>Name in file</th></tr></thead>
        <tbody>
          {ids.map((id) => (
            <tr key={id} style={{ borderTop: `1px solid ${colors.line}` }}>
              <td style={{ ...td, fontFamily: "'IBM Plex Mono', monospace" }}>{id}</td>
              <td style={td}>{names[id] || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Preview({ preview, onCommitted, onDiscarded, setError }) {
  const [tab, setTab] = useState('issues');
  const [selected, setSelected] = useState(() => (preview.sheets || []).filter((s) => !s.blocked).map((s) => s.sheet));
  const [confirmLarge, setConfirmLarge] = useState(false);
  const [ackDept, setAckDept] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [committing, setCommitting] = useState(false);
  const [key] = useState(uid);
  const counts = preview.counts || {};
  const [issueCodes, setIssueCodes] = useState([]);
  useEffect(() => {
    let dead = false;
    setIssueCodes([]);
    fetchLeaveIssues(preview.import_id, { limit: 1000 })
      .then((d) => { if (!dead) setIssueCodes(d.issues.map((i) => i.code)); })
      .catch(() => {});
    return () => { dead = true; };
  }, [preview.import_id]);
  const blockedSelected = (preview.sheets || []).some((s) => s.blocked && selected.includes(s.sheet));
  const largeChange = issueCodes.includes('LARGE_CHANGE');
  const deptMismatch = issueCodes.includes('DEPARTMENT_MISMATCH');
  const committed = preview.status === 'committed';
  const canCommit = !committed && preview.status === 'preview_ready'
    && selected.length > 0 && !blockedSelected
    && (!largeChange || confirmLarge) && (!deptMismatch || ackDept);
  const blockReason = committed ? 'Already committed.'
    : preview.status !== 'preview_ready' ? `Import is ${preview.status}.`
    : selected.length === 0 ? 'Select at least one sheet.'
    : blockedSelected ? 'A blocked sheet is selected — deselect it or fix the file.'
    : largeChange && !confirmLarge ? 'Large-change guard: tick “I expect this many changes”.'
    : deptMismatch && !ackDept ? 'Department label is unexpected — tick to acknowledge.'
    : null;

  async function doCommit() {
    setCommitting(true);
    setError(null);
    try {
      const res = await commitLeaveImport(preview.import_id, {
        sheets: selected, confirm_large_change: confirmLarge,
        acknowledge_department: ackDept, idempotency_key: key,
      });
      onCommitted(res);
    } catch (e) {
      setError(errText(e));
    } finally {
      setCommitting(false);
      setConfirming(false);
    }
  }

  async function doDiscard() {
    setError(null);
    try {
      await discardLeaveImport(preview.import_id);
      onDiscarded();
    } catch (e) {
      setError(errText(e));
    }
  }

  return (
    <section style={card}>
      <h3 style={{ fontSize: 15, fontWeight: 600, margin: '0 0 12px' }}>
        Preview — {preview.original_filename} <span style={{ color: colors.muted, fontWeight: 400 }}>#{preview.import_id}</span>
      </h3>
      <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', marginBottom: 16, fontSize: 13 }}>
        {[['Period', `${preview.period_start} – ${preview.period_end}`],
          ['Coverage through', preview.coverage_through || '—'],
          ['New / changed / unchanged', `${counts.new ?? 0} / ${counts.changed ?? 0} / ${counts.unchanged ?? 0}`],
          ['Employees', counts.employees ?? 0],
        ].map(([label, value]) => (
          <div key={label}>
            <div style={{ fontSize: 12, color: colors.muted }}>{label}</div>
            <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 15 }}>{value}</div>
          </div>
        ))}
      </div>
      <SheetTable sheets={preview.sheets} selected={selected} setSelected={setSelected} />
      <div style={{ display: 'flex', gap: 4, margin: '16px 0', borderBottom: `1px solid ${colors.line}` }}>
        {[['issues', 'Issues'], ['changes', 'Changes'], ['unmatched', 'Unmatched employees'], ['conflicts', 'Conflicts']].map(([k, label]) => (
          <button key={k} type="button" onClick={() => setTab(k)}
            style={{ ...btn, border: 'none', borderBottom: tab === k ? `2px solid ${colors.select}` : '2px solid transparent', borderRadius: 0, color: tab === k ? colors.select : colors.muted, fontWeight: tab === k ? 600 : 500 }}>
            {label}
          </button>
        ))}
      </div>
      {tab === 'issues' && <IssuesTab importId={preview.import_id} />}
      {tab === 'changes' && <ChangesTab importId={preview.import_id} />}
      {tab === 'unmatched' && <UnmatchedTab preview={preview} />}
      {tab === 'conflicts' && <ChangesTab importId={preview.import_id} presentLikeOnly />}
      <div style={{ marginTop: 16, padding: 12, background: colors.paper, border: `1px solid ${colors.line}`, borderRadius: 4 }}>
        {largeChange && (
          <label style={{ display: 'block', fontSize: 13, marginBottom: 8 }}>
            <input type="checkbox" checked={confirmLarge} onChange={(e) => setConfirmLarge(e.target.checked)} /> I expect this many changes
          </label>
        )}
        {deptMismatch && (
          <label style={{ display: 'block', fontSize: 13, marginBottom: 8 }}>
            <input type="checkbox" checked={ackDept} onChange={(e) => setAckDept(e.target.checked)} /> Department label looks right
          </label>
        )}
        {!confirming ? (
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <button type="button" style={canCommit ? primaryBtn : btn} disabled={!canCommit || committing}
              onClick={() => setConfirming(true)}>
              {committing ? 'Committing…' : committed ? 'Committed' : 'Commit'}
            </button>
            {!committed && preview.status === 'preview_ready' && (
              <button type="button" style={btn} onClick={doDiscard}>Discard</button>
            )}
            {blockReason && <span style={{ fontSize: 12.5, color: colors.muted }}>{blockReason}</span>}
          </div>
        ) : (
          <div style={{ fontSize: 13 }}>
            Commit <strong>{selected.length} sheet(s)</strong> ({counts.new ?? 0} new, {counts.changed ?? 0} changed)?
            {' '}<button type="button" style={primaryBtn} disabled={committing} onClick={doCommit}>Confirm commit</button>
            {' '}<button type="button" style={btn} disabled={committing} onClick={() => setConfirming(false)}>Back</button>
          </div>
        )}
      </div>
    </section>
  );
}

function History({ onView, refreshKey, setError }) {
  const [items, setItems] = useState(null);
  const [confirmRevert, setConfirmRevert] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = () => {
    fetchLeaveImportHistory()
      .then(setItems)
      .catch((e) => setError(errText(e)));
  };
  useEffect(load, [refreshKey]);
  async function doRevert(id) {
    setBusy(true);
    setError(null);
    try {
      const res = await revertLeaveImport(id);
      setConfirmRevert(null);
      setError(null);
      load();
      onView(id, `Reverted (${res.restored} restored, ${res.skipped} skipped).`);
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(false);
    }
  }
  if (!items) return <div style={{ color: colors.muted, fontSize: 13 }}>Loading history…</div>;
  const latestCommitted = items.find((i) => i.status === 'committed');
  return (
    <section style={card}>
      <h3 style={{ fontSize: 15, fontWeight: 600, margin: '0 0 12px' }}>History</h3>
      {items.length === 0 && <div style={{ color: colors.muted, fontSize: 13 }}>No imports yet.</div>}
      {items.length > 0 && (
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead><tr>
            <th style={th}>ID</th><th style={th}>File</th><th style={th}>By</th><th style={th}>Uploaded</th>
            <th style={th}>Status</th><th style={{ ...th, textAlign: 'right' }}>New/Changed</th><th style={th}>Actions</th>
          </tr></thead>
          <tbody>
            {items.map((i) => (
              <tr key={i.id} style={{ borderTop: `1px solid ${colors.line}` }}>
                <td style={{ ...td, fontFamily: "'IBM Plex Mono', monospace" }}>{i.id}</td>
                <td style={td}>{i.original_filename}</td>
                <td style={td}>{i.uploaded_by || '—'}</td>
                <td style={td}>{(i.uploaded_at || '').slice(0, 16).replace('T', ' ')}</td>
                <td style={td}>{i.status}</td>
                <td style={{ ...td, textAlign: 'right' }}>
                  {(i.counts?.new ?? 0)}/{(i.counts?.changed ?? 0)}
                </td>
                <td style={td}>
                  <button type="button" style={{ ...btn, padding: '4px 10px', fontSize: 12 }} onClick={() => onView(i.id)}>View</button>
                  {i.status === 'committed' && latestCommitted && latestCommitted.id === i.id && (
                    confirmRevert === i.id
                      ? <span> <button type="button" style={{ ...dangerBtn, padding: '4px 10px', fontSize: 12 }} disabled={busy} onClick={() => doRevert(i.id)}>Confirm revert</button>
                        <button type="button" style={{ ...btn, padding: '4px 10px', fontSize: 12 }} onClick={() => setConfirmRevert(null)}>Cancel</button></span>
                      : <span> <button type="button" style={{ ...btn, padding: '4px 10px', fontSize: 12 }} onClick={() => setConfirmRevert(i.id)}>Revert</button></span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

const KIND_OPTIONS = ['working', 'weekend', 'holiday', 'not_employed', 'leave', 'on_duty', 'unknown'];

function TypesAdmin({ setError }) {
  const [types, setTypes] = useState(null);
  const [form, setForm] = useState({ code: '', label: '', kind: 'leave', leave_group: '', paid: '', sensitive: false });
  const [repro, setRepro] = useState(null);
  const load = () => fetchLeaveTypes().then(setTypes).catch((e) => setError(errText(e)));
  useEffect(() => { load(); }, []);
  async function save(e) {
    e.preventDefault();
    setError(null);
    try {
      await putLeaveType({
        code: form.code, label: form.label || undefined, kind: form.kind,
        leave_group: form.leave_group || null,
        paid: form.paid === '' ? null : form.paid === 'true',
        sensitive: !!form.sensitive,
      });
      setForm({ code: '', label: '', kind: 'leave', leave_group: '', paid: '', sensitive: false });
      load();
    } catch (err) {
      setError(errText(err));
    }
  }
  async function reprocess() {
    setError(null);
    try {
      setRepro(await reprocessLeave());
    } catch (e) {
      setError(errText(e));
    }
  }
  return (
    <section style={card}>
      <h3 style={{ fontSize: 15, fontWeight: 600, margin: '0 0 12px' }}>Leave types</h3>
      {!types ? <div style={{ color: colors.muted, fontSize: 13 }}>Loading…</div> : (
        <table style={{ width: '100%', borderCollapse: 'collapse', marginBottom: 12 }}>
          <thead><tr>
            <th style={th}>Code</th><th style={th}>Label</th><th style={th}>Kind</th>
            <th style={th}>Group</th><th style={th}>Sensitive</th>
          </tr></thead>
          <tbody>
            {types.map((t) => (
              <tr key={t.code} style={{ borderTop: `1px solid ${colors.line}` }}>
                <td style={{ ...td, fontFamily: "'IBM Plex Mono', monospace" }}>{t.code}</td>
                <td style={td}>{t.label}</td>
                <td style={td}>{t.kind}</td>
                <td style={td}>{t.leave_group || '—'}</td>
                <td style={td}>{t.sensitive ? 'yes' : 'no'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <form onSubmit={save} style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'end', fontSize: 13 }}>
        <label>Code<br /><input value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} required style={{ fontFamily: 'inherit', padding: 6 }} /></label>
        <label>Label<br /><input value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} style={{ fontFamily: 'inherit', padding: 6 }} /></label>
        <label>Kind<br /><select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })} style={{ fontFamily: 'inherit', padding: 6 }}>
          {KIND_OPTIONS.map((k) => <option key={k} value={k}>{k}</option>)}
        </select></label>
        <label>Group<br /><input value={form.leave_group} onChange={(e) => setForm({ ...form, leave_group: e.target.value })} placeholder="annual/sick/…" style={{ fontFamily: 'inherit', padding: 6 }} /></label>
        <label>Sensitive<br /><input type="checkbox" checked={form.sensitive} onChange={(e) => setForm({ ...form, sensitive: e.target.checked })} /></label>
        <button type="submit" style={btn}>Save mapping</button>
        <button type="button" style={btn} onClick={reprocess}>Reprocess history</button>
        {repro && <span style={{ color: colors.muted }}>Reprocessed: {repro.updated}/{repro.scanned} rows updated.</span>}
      </form>
    </section>
  );
}

export default function LeaveImport({ scope }) {
  const { coverage } = scope;
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);

  // Resume: open the latest live preview, so a reload lands back here.
  useEffect(() => {
    let dead = false;
    fetchLeaveImportHistory(10)
      .then((items) => {
        const open = items.find((i) => i.status === 'preview_ready' || i.status === 'parsing');
        if (open && !dead) {
          fetchLeaveImport(open.id).then((p) => { if (!dead) setPreview(p); }).catch(() => {});
        }
      })
      .catch(() => {});
    return () => { dead = true; };
  }, []);

  // Poll while the server is still working (future worker); harmless otherwise.
  useEffect(() => {
    if (!preview || (preview.status !== 'parsing' && preview.status !== 'committing')) return undefined;
    const t = setInterval(() => {
      fetchLeaveImport(preview.import_id).then(setPreview).catch(() => {});
    }, 2000);
    return () => clearInterval(t);
  }, [preview?.import_id, preview?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  function viewImport(id, note) {
    setError(null);
    setNotice(note || null);
    fetchLeaveImport(id).then((p) => { setPreview(p); setRefreshKey((k) => k + 1); }).catch((e) => setError(errText(e)));
  }

  return (
    <>
      <h2 style={{ fontSize: 16, fontWeight: 600, margin: '0 0 14px' }}>Leave data</h2>
      <CoverageBanner coverage={coverage} />
      {error && <div style={{ ...card, borderColor: colors.alert, color: colors.alert, fontSize: 13 }}>{error}</div>}
      {notice && <div style={{ ...card, borderColor: colors.good, fontSize: 13 }}>{notice}</div>}
      <UploadPanel
        busy={busy} setBusy={setBusy} setError={setError}
        onUploaded={(p) => { setPreview(p); setRefreshKey((k) => k + 1); }} />
      {preview && (
        <Preview
          key={preview.import_id}
          preview={preview}
          setError={setError}
          onCommitted={(res) => {
            setNotice(`Committed: ${res.committed_rows} days written, coverage through ${res.coverage_through}.`);
            setRefreshKey((k) => k + 1);
            fetchLeaveImport(res.import_id).then(setPreview).catch(() => {});
          }}
          onDiscarded={() => {
            setPreview(null);
            setNotice('Preview discarded.');
            setRefreshKey((k) => k + 1);
          }} />
      )}
      <History onView={viewImport} refreshKey={refreshKey} setError={setError} />
      <TypesAdmin setError={setError} />
    </>
  );
}
