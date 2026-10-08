// Exceptions (#/exceptions): merged Anomalies & Leave.
import React, { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { colors } from '../theme.js';
import { classifyDay, punchCount, statusLabel, toCSV, shortDateISO } from '../metrics.js';
import { LeaveBanner } from '../Dashboard.jsx';
import { EmptyState } from './Teams.jsx';

const th = { textAlign: 'left', padding: '10px 16px', color: colors.muted, fontWeight: 500, fontSize: 12 };
const td = { padding: '9px 16px', fontSize: 13 };
const PAGE = 100;

const TYPES = ['all', 'no_record', 'missing_checkout', 'off_shift', 'late_in', 'early_out', 'unmatched_leave'];
const TYPE_LABEL = { all: 'All', no_record: 'No record', missing_checkout: 'Missing check-out', off_shift: 'Off-shift', late_in: 'Late in', early_out: 'Early out', unmatched_leave: 'Unmatched leave' };

function buildEntries(rows, scopeDates, neverIds, ctx) {
  const byEmp = new Map();
  for (const r of rows) {
    if (!byEmp.has(r.employeeId)) byEmp.set(r.employeeId, { rec: r, byDate: new Map() });
    byEmp.get(r.employeeId).byDate.set(r.date, r);
  }
  const entries = [];
  const hasLate = rows.some((r) => r.late);
  const hasEarly = rows.some((r) => r.early);
  for (const { rec: info, byDate } of byEmp.values()) {
    for (const d of scopeDates) {
      const rec = byDate.get(d) || { date: d, leaves: [] };
      const st = classifyDay(rec, ctx);
      const base = { date: d, employeeId: info.employeeId, name: info.name, team: info.team, rec };
      if (st === 'no_record' && !neverIds.has(info.employeeId)) {
        entries.push({ ...base, type: 'no_record', detail: 'No punch, no leave' });
      }
      if (st === 'missing_checkout') {
        entries.push({ ...base, type: 'missing_checkout', detail: `In ${rec.checkIn || rec.checkOut || '—'}, no check-out` });
      }
      if ((st === 'present' || st === 'missing_checkout') && rec.shiftAnomaly) {
        entries.push({ ...base, type: 'off_shift', detail: `Punch outside ${rec.assignedShift || 'assigned'} shift` });
      }
      if (rec.late) entries.push({ ...base, type: 'late_in', detail: `In ${rec.checkIn}` });
      if (rec.early) entries.push({ ...base, type: 'early_out', detail: `Out ${rec.checkOut}` });
      if (ctx.leaveLoaded && (rec.leaves || []).some((l) => (l.status || 'approved') === 'approved') && punchCount(rec) > 0) {
        entries.push({ ...base, type: 'unmatched_leave', detail: `On leave but punched ${rec.checkIn || ''}–${rec.checkOut || ''}` });
      }
    }
  }
  entries.sort((a, b) => b.date.localeCompare(a.date) || a.name.localeCompare(b.name));
  return { entries, hasLate, hasEarly };
}

export default function Exceptions({ scope }) {
  const { rows, scopeDates, agg, ctx, leaveLoaded, update } = scope;
  const [page, setPage] = useState(0);
  const neverIds = useMemo(() => new Set(agg.employees.filter((e) => e.neverPunched).map((e) => e.id)), [agg.employees]);
  const { entries, hasLate, hasEarly } = useMemo(
    () => buildEntries(rows, scopeDates, neverIds, ctx), [rows, scopeDates, neverIds, ctx]);

  const type = TYPES.includes(scope.filters.type) ? scope.filters.type : 'all';
  const counts = {};
  for (const e of entries) counts[e.type] = (counts[e.type] || 0) + 1;
  const filtered = type === 'all' ? entries : entries.filter((e) => e.type === type);
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE));
  const cur = Math.min(page, pages - 1);
  const slice = filtered.slice(cur * PAGE, cur * PAGE + PAGE);

  function openEmp(e) {
    update({ day: e.date }, { path: `/employees/${e.employeeId}` });
  }

  function exportCSV() {
    const header = ['date', 'employee_id', 'name', 'team', 'type', 'detail'];
    const body = filtered.map((e) => [e.date, e.employeeId, e.name, e.team, e.type, e.detail]);
    const blob = new Blob([toCSV(header, body)], { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'exceptions.csv';
    a.click();
    URL.revokeObjectURL(a.href);
  }

  const chip = (t) => {
    const disabled = t === 'unmatched_leave' && !leaveLoaded;
    const hidden = (t === 'late_in' && !hasLate) || (t === 'early_out' && !hasEarly);
    if (hidden) return null;
    const active = type === t;
    const label = t === 'no_record' ? statusLabel('no_record', leaveLoaded) : TYPE_LABEL[t];
    return (
      <button key={t} disabled={disabled} onClick={() => { setPage(0); update({ type: t === 'all' ? '' : t }); }}
        title={disabled ? 'Available once leave data is loaded' : ''}
        style={{
          fontFamily: 'inherit', fontSize: 12.5, padding: '7px 14px', cursor: disabled ? 'not-allowed' : 'pointer',
          border: `1px solid ${active ? colors.ink : colors.line}`, opacity: disabled ? 0.5 : 1,
          background: active ? colors.ink : colors.panel, color: active ? colors.paper : colors.ink, borderRadius: 20,
        }}>
        {label}{t !== 'all' && counts[t] ? ` (${counts[t]})` : ''}
      </button>
    );
  };

  return (
    <>
      {!leaveLoaded && <LeaveBanner />}
      {!leaveLoaded && (
        <div style={{ border: `1px solid ${colors.line}`, borderRadius: 4, background: colors.panel, padding: '12px 16px', fontSize: 13, marginBottom: 16, color: colors.muted }}>
          Leave reconciliation arrives with the Zoho leave import. Until then, no-record days cannot be separated from approved leave.
        </div>
      )}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16, alignItems: 'center' }}>
        {TYPES.map(chip)}
        <button onClick={exportCSV} style={{
          marginLeft: 'auto', fontFamily: 'inherit', fontSize: 12.5, padding: '7px 14px', cursor: 'pointer',
          border: `1px solid ${colors.line}`, borderRadius: 4, background: colors.panel,
        }}>
          Export CSV
        </button>
      </div>
      {agg.neverPunchedCount > 0 && (
        <div style={{ fontSize: 13, color: colors.muted, marginBottom: 12 }}>
          {agg.neverPunchedCount} employee{agg.neverPunchedCount === 1 ? '' : 's'} have no punches in this period. See{' '}
          <Link to="/employees?group=nopunch" style={{ color: colors.select }}>Employees → No punches group</Link>.
        </div>
      )}
      {filtered.length === 0 ? (
        <EmptyState scope={scope} />
      ) : (
        <>
          <div style={{ border: `1px solid ${colors.line}`, borderRadius: 4, overflow: 'hidden', background: colors.panel }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead><tr>
                <th style={th}>Date</th><th style={th}>Employee</th><th style={th}>Team</th>
                <th style={th}>Type</th><th style={th}>Detail</th><th style={th}>Open</th>
              </tr></thead>
              <tbody>
                {slice.map((e, i) => (
                  <tr key={`${e.employeeId}-${e.date}-${e.type}`} style={{ borderTop: `1px solid ${colors.line}`, background: i % 2 ? 'rgba(0,0,0,0.015)' : 'transparent' }}>
                    <td style={{ ...td, color: colors.muted }}>{shortDateISO(e.date)}</td>
                    <td style={{ ...td, fontWeight: 500 }}>{e.name}</td>
                    <td style={{ ...td, fontSize: 12.5 }}>{e.team}</td>
                    <td style={td}>{e.type === 'no_record' ? statusLabel('no_record', leaveLoaded) : TYPE_LABEL[e.type]}</td>
                    <td style={{ ...td, color: colors.muted }}>{e.detail}</td>
                    <td style={td}><button onClick={() => openEmp(e)} style={{ background: 'none', border: 'none', color: colors.select, cursor: 'pointer', fontSize: 13 }}>Open</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {pages > 1 && (
            <div style={{ display: 'flex', gap: 12, alignItems: 'center', fontSize: 12.5, color: colors.muted, marginTop: 8 }}>
              <button disabled={cur === 0} onClick={() => setPage(cur - 1)}>Prev</button>
              <span>Showing {cur * PAGE + 1}–{Math.min((cur + 1) * PAGE, filtered.length)} of {filtered.length}</span>
              <button disabled={cur >= pages - 1} onClick={() => setPage(cur + 1)}>Next</button>
            </div>
          )}
        </>
      )}
    </>
  );
}
