// Employees (#/employees, #/employees/:employeeId): master-detail,
// no-punches group, pagination, heatmap mode, drawer with day table + CSV.
import React, { useMemo, useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { colors } from '../theme.js';
import {
  statusLabel, classifyDay, outSuffix, toCSV, shortDateISO, day3ISO,
} from '../metrics.js';
import { LeaveBanner } from '../Dashboard.jsx';
import AttendanceHeatmap from '../components/Heatmap.jsx';
import { EmptyState } from './Teams.jsx';

const th = { textAlign: 'left', padding: '10px 16px', color: colors.muted, fontWeight: 500, fontSize: 12 };
const thR = { ...th, textAlign: 'right' };
const td = { padding: '9px 16px', fontSize: 13 };

const PAGE = 100;

function applySort(list, sort) {
  const [key = 'noRecord', dir = 'desc'] = (sort || 'noRecord:desc').split(':');
  const val = (e) => (key === 'name' ? e.name : key === 'team' ? e.team : e[key] ?? 0);
  return [...list].sort((a, b) => {
    const av = val(a), bv = val(b);
    const cmp = typeof av === 'string' ? av.localeCompare(bv) : av - bv;
    return dir === 'asc' ? cmp : -cmp;
  });
}

export default function Employees({ scope }) {
  const { employeeId } = useParams();
  const { agg, filters, scopeDates, rows, ctx, leaveLoaded, update } = scope;
  const noRecordLabel = statusLabel('no_record', leaveLoaded);

  const [page, setPage] = useState(0);
  const [groupOpen, setGroupOpen] = useState(filters.group === 'nopunch');
  useEffect(() => { setPage(0); }, [filters.month, filters.range, filters.day, filters.shift, filters.teams, filters.q]);
  useEffect(() => { if (filters.group === 'nopunch') setGroupOpen(true); }, [filters.group]);

  const q = filters.q.toLowerCase();
  const main = agg.employees.filter((e) => !e.neverPunched)
    .filter((e) => !q || e.name.toLowerCase().includes(q) || e.id.startsWith(filters.q));
  const punched = agg.employees.filter((e) => e.neverPunched)
    .filter((e) => !q || e.name.toLowerCase().includes(q) || e.id.startsWith(filters.q));
  const sorted = applySort(main, filters.sort);
  const pages = Math.max(1, Math.ceil(sorted.length / PAGE));
  const cur = Math.min(page, pages - 1);
  const slice = sorted.slice(cur * PAGE, cur * PAGE + PAGE);

  const selected = employeeId ? agg.employees.find((e) => e.id === employeeId) : null;
  const wide = typeof window !== 'undefined' && window.innerWidth >= 1100;

  function toggleSort(key) {
    const [ck, cd] = (filters.sort || 'noRecord:desc').split(':');
    update({ sort: ck === key && cd === 'desc' ? `${key}:asc` : `${key}:desc` });
  }
  const sortMark = (k) => {
    const [ck, cd] = (filters.sort || 'noRecord:desc').split(':');
    return ck === k ? (cd === 'asc' ? ' ↑' : ' ↓') : '';
  };

  return (
    <>
      {!leaveLoaded && <LeaveBanner />}
      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start', flexWrap: wide ? 'nowrap' : 'wrap' }}>
        <section style={{ flex: 1, minWidth: wide ? 640 : 0 }}>
          <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' }}>
            <input value={filters.q} onChange={(e) => update({ q: e.target.value }, { replace: true })}
              placeholder="Search name or ID" style={{
                fontFamily: 'inherit', fontSize: 13, padding: '7px 10px', border: `1px solid ${colors.line}`,
                borderRadius: 4, background: colors.panel, color: colors.ink, width: 220,
              }} />
            <div style={{ display: 'flex', gap: 4 }} role="group" aria-label="View">
              {['list', 'heatmap'].map((v) => (
                <button key={v} onClick={() => update({ view: v })}
                  style={{
                    fontFamily: 'inherit', fontSize: 12.5, padding: '7px 12px', cursor: 'pointer',
                    border: `1px solid ${filters.view === v ? colors.ink : colors.line}`,
                    background: filters.view === v ? colors.ink : colors.panel,
                    color: filters.view === v ? colors.paper : colors.ink, borderRadius: 20,
                  }}>
                  {v === 'list' ? 'List' : 'Heatmap'}
                </button>
              ))}
            </div>
          </div>

          {filters.view === 'heatmap' ? (
            <AttendanceHeatmap employees={main} rows={rows} dates={scopeDates} ctx={ctx} scope={scope} groupByTeam />
          ) : sorted.length === 0 && punched.length === 0 ? (
            <EmptyState scope={scope} />
          ) : (
            <>
              <div style={{ border: `1px solid ${colors.line}`, borderRadius: 4, overflow: 'hidden', background: colors.panel }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead style={{ position: 'sticky', top: 57, background: colors.panel }}>
                    <tr>
                      {[['name', 'Name'], ['team', 'Team']].map(([k, l]) => (
                        <th key={k} onClick={() => toggleSort(k)} style={{ ...th, cursor: 'pointer' }}>{l}{sortMark(k)}</th>
                      ))}
                      {[['present', 'Present'], ['leave', 'On leave'], ['noRecord', noRecordLabel], ['missing', 'Missing out'], ['avgHours', 'Avg hrs/day'], ['overtime', 'OT hrs'], ['offshift', 'Off-shift']].map(([k, l]) => (
                        <th key={k} onClick={() => toggleSort(k)} style={{ ...thR, cursor: 'pointer' }}>{l}{sortMark(k)}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {slice.map((e, i) => (
                      <tr key={e.id} onClick={() => update({}, { path: `/employees/${e.id}` })}
                        style={{
                          borderTop: `1px solid ${colors.line}`, cursor: 'pointer',
                          background: e.id === employeeId ? `${colors.select}22` : (i % 2 ? 'rgba(0,0,0,0.015)' : 'transparent'),
                        }}>
                        <td style={td}>{e.name}<span style={{ color: colors.muted, fontFamily: "'IBM Plex Mono', monospace", fontSize: 11.5, marginLeft: 8 }}>{e.id}</span></td>
                        <td style={{ ...td, fontSize: 12.5 }}>{e.team}</td>
                        <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{e.present} / {e.expected}</td>
                        <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace", color: colors.warn }}>{e.leave || '—'}</td>
                        <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{e.noRecord || '—'}</td>
                        <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{e.missing || '—'}</td>
                        <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{e.avgHours || '—'}</td>
                        <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{e.overtime ? e.overtime.toFixed(1) : '—'}</td>
                        <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{e.offshift || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {pages > 1 && (
                <div style={{ display: 'flex', gap: 12, alignItems: 'center', fontSize: 12.5, color: colors.muted, marginTop: 8 }}>
                  <button disabled={cur === 0} onClick={() => setPage(cur - 1)} style={pageBtn(cur === 0)}>Prev</button>
                  <span>Showing {cur * PAGE + 1}–{Math.min((cur + 1) * PAGE, sorted.length)} of {sorted.length}</span>
                  <button disabled={cur >= pages - 1} onClick={() => setPage(cur + 1)} style={pageBtn(cur >= pages - 1)}>Next</button>
                </div>
              )}
            </>
          )}

          {punched.length > 0 && (
            <div style={{ border: `1px solid ${colors.line}`, borderRadius: 4, background: colors.panel, marginTop: 12 }}>
              <button onClick={() => setGroupOpen((o) => !o)} style={{
                width: '100%', textAlign: 'left', background: 'none', border: 'none', cursor: 'pointer',
                padding: '12px 16px', fontSize: 13.5, fontWeight: 600, color: colors.ink, fontFamily: 'inherit',
              }}>
                {groupOpen ? '▾' : '▸'} No punches in this period ({punched.length})
              </button>
              {groupOpen && (
                <div style={{ padding: '0 16px 12px', fontSize: 12.5, color: colors.muted }}>
                  These employees have no biometric records for any working day in this range. Check enrolment or user-ID mapping before treating this as absence.
                  {punched.slice(0, 50).map((e) => (
                    <div key={e.id} style={{ padding: '4px 0', borderTop: `1px solid ${colors.line}` }}>
                      <span style={{ color: colors.ink }}>{e.name}</span>
                      <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11.5, marginLeft: 8 }}>{e.id}</span>
                      <span style={{ marginLeft: 8 }}>{e.team}</span>
                    </div>
                  ))}
                  {punched.length > 50 && <div>…and {punched.length - 50} more. Narrow filters to list everyone.</div>}
                </div>
              )}
            </div>
          )}
        </section>

        {selected && (
          <Drawer employee={selected} scope={scope} overlay={!wide} />
        )}
      </div>
      {!selected && employeeId && (
        <div style={{ marginTop: 12, fontSize: 13, color: colors.muted }}>
          Employee not found in this view.
        </div>
      )}
    </>
  );
}

function pageBtn(disabled) {
  return {
    fontFamily: 'inherit', fontSize: 12.5, padding: '6px 12px', cursor: disabled ? 'default' : 'pointer',
    border: `1px solid ${colors.line}`, borderRadius: 16,
    background: colors.panel, color: disabled ? colors.muted : colors.ink, opacity: disabled ? 0.6 : 1,
  };
}

function Drawer({ employee: e, scope, overlay }) {
  const { scopeDates, rows, ctx, leaveLoaded, filters, update } = scope;
  const byDate = new Map(rows.filter((r) => r.employeeId === e.id).map((r) => [r.date, r]));
  const dayRows = scopeDates.map((d) => {
    const rec = byDate.get(d) || { date: d, leaves: [] };
    return { date: d, rec, status: classifyDay(rec, ctx) };
  });

  function exportCSV() {
    const header = ['date', 'day', 'status', 'in', 'out', 'hours'];
    const body = dayRows.map(({ date, rec, status }) => [
      date, day3ISO(date), statusLabel(status, leaveLoaded),
      rec.checkIn || '', (rec.checkOut || '') + (rec.checkOut ? outSuffix(rec).trim() : ''), rec.hours ?? '',
    ]);
    const blob = new Blob([toCSV(header, body)], { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `attendance-${e.id}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  return (
    <aside style={overlay ? {
      position: 'fixed', top: 0, right: 0, bottom: 0, width: 'min(480px, 100vw)', zIndex: 100,
      background: colors.panel, borderLeft: `1px solid ${colors.line}`, overflowY: 'auto', padding: 16,
    } : {
      width: 420, flexShrink: 0, border: `1px solid ${colors.select}`, borderRadius: 4,
      background: colors.panel, maxHeight: '80vh', overflowY: 'auto', position: 'sticky', top: 120,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
        <div>
          <div style={{ fontWeight: 600, fontSize: 15 }}>{e.name}</div>
          <div style={{ fontSize: 12.5, color: colors.muted }}>{e.id} · {e.team}</div>
        </div>
        <button onClick={() => update({}, { path: '/employees' })} aria-label="Close"
          style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 16, color: colors.muted }}>×</button>
      </div>
      <div style={{ display: 'flex', gap: 16, fontSize: 12.5, marginBottom: 12, flexWrap: 'wrap' }}>
        <span>Rate <strong style={{ fontFamily: "'IBM Plex Mono', monospace" }}>{e.attendanceRate === null ? '—' : `${Math.round(e.attendanceRate * 1000) / 10}%`}</strong></span>
        <span>Present <strong style={{ fontFamily: "'IBM Plex Mono', monospace" }}>{e.present} / {e.expected}</strong></span>
        <span>{statusLabel('no_record', leaveLoaded)} <strong style={{ fontFamily: "'IBM Plex Mono', monospace" }}>{e.noRecord}</strong></span>
        <span>Avg <strong style={{ fontFamily: "'IBM Plex Mono', monospace" }}>{e.avgHours || '—'}</strong></span>
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
        <thead><tr>
          <th style={th}>Day</th><th style={th}>Date</th><th style={th}>Status</th>
          <th style={thR}>In</th><th style={thR}>Out</th><th style={thR}>Hrs</th>
        </tr></thead>
        <tbody>
          {dayRows.map(({ date, rec, status }) => {
            const muted = status === 'weekend' || status === 'holiday';
            return (
              <tr key={date} id={`day-${date}`}
                ref={(el) => { if (el && filters.day === date) el.scrollIntoView({ block: 'nearest' }); }}
                style={{
                  borderTop: `1px solid ${colors.line}`,
                  background: filters.day === date ? `${colors.select}14` : 'transparent',
                  borderLeft: status === 'in_progress' ? `3px solid ${colors.good}` : '3px solid transparent',
                }}>
                <td style={td}>{day3ISO(date)}</td>
                <td style={{ ...td, color: colors.muted }}>{shortDateISO(date)}</td>
                <td style={{ ...td, color: muted ? colors.muted : colors.ink }}>{statusLabel(status, leaveLoaded)}</td>
                <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{rec.checkIn || '—'}</td>
                <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{rec.checkOut ? rec.checkOut + outSuffix(rec) : '—'}</td>
                <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{rec.hours || '—'}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <button onClick={exportCSV} style={{
        marginTop: 12, fontFamily: 'inherit', fontSize: 13, padding: '7px 14px', cursor: 'pointer',
        border: `1px solid ${colors.line}`, borderRadius: 4, background: colors.panel,
      }}>
        Export CSV
      </button>
    </aside>
  );
}
