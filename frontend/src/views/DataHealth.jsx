// Data health (#/data-health): renamed Sync check + summary card (§6.6).
import React, { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { colors } from '../theme.js';
import { isWeekendISO, shortDateISO, leaveQuality } from '../metrics.js';
import { monthLabel } from '../filters.js';

function nairobi(s) {
  if (!s) return '—';
  const d = new Date(s.length === 10 ? s + 'T00:00:00Z' : s);
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Africa/Nairobi', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
  }).format(d);
}

function age(s) {
  if (!s) return '';
  const ms = Date.now() - new Date(s).getTime();
  const h = ms / 3600000;
  if (h < 1) return `${Math.max(1, Math.round(ms / 60000))}m ago`;
  if (h < 48) return `${Math.round(h)}h ago`;
  return `${Math.round(h / 24)}d ago`;
}

const th = { textAlign: 'left', padding: '10px 16px', color: colors.muted, fontWeight: 500, fontSize: 12 };
const thR = { ...th, textAlign: 'right' };
const td = { padding: '9px 16px', fontSize: 13 };

export default function DataHealth({ scope }) {
  const { coverage, agg, update, leaveActive, rows, scopeDates, ctx, rosterInScope } = scope;
  const last = coverage?.sync_log?.[0];
  const lastAgeH = last ? (Date.now() - new Date(last.run_at).getTime()) / 3600000 : null;
  const ageTone = lastAgeH === null ? colors.muted : lastAgeH > 72 ? colors.alert : lastAgeH > 24 ? '#c58a1b' : colors.good;
  const sync = coverage?.sync_state?.ingestor;
  const syncTone = !sync ? colors.muted : sync.state === 'healthy' ? colors.good : sync.state === 'degraded' ? '#c58a1b' : colors.alert;

  const counts = (coverage?.per_date ?? []).map((d) => d.count).sort((a, b) => a - b);
  const typical = counts.length ? counts[Math.floor(counts.length / 2)] : 0;
  const leaveThrough = coverage?.leave_coverage?.through_date || null;
  const quality = useMemo(() => (
    leaveActive ? leaveQuality(rows, scopeDates, ctx, rosterInScope) : null
  ), [leaveActive, rows, scopeDates, ctx, rosterInScope]);

  return (
    <>
      <h2 style={{ fontSize: 16, fontWeight: 600, margin: '0 0 14px' }}>Data health</h2>
      <section style={{ display: 'flex', flexWrap: 'wrap', gap: 0, marginBottom: 24, border: `1px solid ${colors.line}`, borderRadius: 4, overflow: 'hidden', background: colors.panel }}>
        {[
          ['Last sync', last ? `${nairobi(last.run_at)} (${age(last.run_at)})` : '—', ageTone],
          ['Poller link', sync ? sync.state : 'unknown', syncTone, null,
            sync?.last_error ? `Since ${nairobi(sync.since)} — ${sync.last_error}` : (sync ? `Since ${nairobi(sync.since)}` : 'no data yet')],
          ['Data range', coverage?.date_min && coverage?.date_max ? `${coverage.date_min} – ${coverage.date_max}` : '—'],
          ['Rows / employees', coverage ? `${coverage.attendance_rows} / ${coverage.employees}` : '—'],
          ['Leave data', leaveThrough ? `Current through ${leaveThrough}` : (coverage?.leave_by_month ?? []).length ? `Loaded (${(coverage.leave_by_month).join(', ')})` : 'Not loaded'],
          ['No punches (filter)', agg.neverPunchedCount, undefined, '/employees?group=nopunch'],
        ].map(([label, value, tone, to, sub], i) => (
          <div key={label} style={{ flex: '1 1 200px', padding: '14px 16px', borderRight: `1px solid ${colors.line}` }}>
            <div style={{ fontSize: 12, color: colors.muted, marginBottom: 6 }}>{label}</div>
            <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 16, color: tone || colors.ink }}>
              {typeof to === 'string' && to.startsWith('/') ? <Link to={to} style={{ color: colors.select }}>{value}</Link> : value}
            </div>
            {sub && <div style={{ fontSize: 11.5, color: colors.muted, marginTop: 4 }}>{sub}</div>}
          </div>
        ))}
      </section>

      <section style={{ marginBottom: 24 }}>
        <h3 style={{ fontSize: 15, fontWeight: 600, margin: '0 0 12px' }}>Per-date coverage</h3>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', background: colors.panel, border: `1px solid ${colors.line}`, borderRadius: 4, padding: 14 }}>
          {(coverage?.per_date ?? []).map((d) => {
            const weekend = isWeekendISO(d.date);
            const thin = typical > 0 && d.count < typical * 0.5;
            const empty = d.count === 0;
            const pastLeave = leaveThrough && d.date > leaveThrough;
            const c = empty ? colors.alert : thin ? '#c58a1b' : colors.good;
            return (
              <div key={d.date} title={`${d.date} — ${d.count} rows (typical: ${typical})${pastLeave ? '; past leave coverage — unverified' : ''}`}
                style={{
                  padding: '6px 10px', borderRadius: 20, fontSize: 12, fontFamily: "'IBM Plex Mono', monospace",
                  background: weekend && !thin && !empty && !pastLeave ? colors.paper : `${c}1F`,
                  color: weekend && !thin && !empty && !pastLeave ? colors.muted : c,
                  border: pastLeave
                    ? `1px dashed ${colors.alert}`
                    : weekend && !thin && !empty ? `1px dashed ${colors.line}` : `1px solid ${c}4D`,
                  fontWeight: 600, cursor: 'pointer',
                }}
                onClick={() => {
                  const m = d.date.slice(0, 7);
                  update({ month: m, range: Number(d.date.slice(8, 10)) <= 15 ? 'h1' : 'h2', day: d.date }, { path: '/' });
                }}>
                {shortDateISO(d.date)} · {d.count}
              </div>
            );
          })}
        </div>
      </section>

      <section style={{ marginBottom: 24 }}>
        <h3 style={{ fontSize: 15, fontWeight: 600, margin: '0 0 12px' }}>Per-month totals</h3>
        <div style={{ border: `1px solid ${colors.line}`, borderRadius: 4, overflow: 'hidden', background: colors.panel }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr><th style={th}>Month</th><th style={thR}>Rows</th><th style={thR}>Dates</th></tr></thead>
            <tbody>
              {(coverage?.per_month ?? []).map((m, i) => {
                const dates = (coverage?.per_date ?? []).filter((d) => d.date.slice(0, 7) === m.month).length;
                return (
                  <tr key={m.month} style={{ borderTop: `1px solid ${colors.line}`, background: i % 2 ? 'rgba(0,0,0,0.015)' : 'transparent' }}>
                    <td style={{ ...td, fontWeight: 500 }}>{monthLabel(m.month)}</td>
                    <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{m.count}</td>
                    <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{dates}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {leaveActive && quality && (
        <section style={{ marginBottom: 24 }}>
          <h3 style={{ fontSize: 15, fontWeight: 600, margin: '0 0 12px' }}>Leave data quality</h3>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 0, marginBottom: 12, border: `1px solid ${colors.line}`, borderRadius: 4, overflow: 'hidden', background: colors.panel }}>
            {[
              ['Leave conflicts', quality.conflictCount, quality.conflictCount > 0 ? colors.alert : colors.good, 'Leave days with a punch or Zoho presence'],
              ['Unverified days', quality.unverifiedDays, quality.unverifiedDays > 0 ? '#c58a1b' : colors.good, 'Past coverage gaps or unknown codes — never absent'],
              ['No leave data', quality.noLeaveData.length, quality.noLeaveData.length > 0 ? '#c58a1b' : colors.good, 'In scope but in no covering import'],
              ['Zoho-only presence', quality.zohoOnly, undefined, 'Zoho P with no biometric punch'],
              ['Zoho-absent punches', quality.zohoAbsentPunch, quality.zohoAbsentPunch > 0 ? colors.alert : undefined, 'Zoho A but biometric punch exists'],
            ].map(([label, value, tone, sub]) => (
              <div key={label} style={{ flex: '1 1 160px', padding: '14px 16px', borderRight: `1px solid ${colors.line}` }}>
                <div style={{ fontSize: 12, color: colors.muted, marginBottom: 6 }}>{label}</div>
                <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 16, color: tone || colors.ink }}>{value}</div>
                <div style={{ fontSize: 11.5, color: colors.muted, marginTop: 4 }}>{sub}</div>
              </div>
            ))}
          </div>
          {(quality.conflicts.length > 0 || quality.unverifiedTop.length > 0 || quality.noLeaveData.length > 0 || quality.disagreements.length > 0) && (
            <div style={{ border: `1px solid ${colors.line}`, borderRadius: 4, overflow: 'hidden', background: colors.panel }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead><tr><th style={th}>Signal</th><th style={th}>Employee</th><th style={th}>Detail</th></tr></thead>
                <tbody>
                  {quality.conflicts.map((c, i) => (
                    <tr key={`c-${i}`} style={{ borderTop: `1px solid ${colors.line}` }}>
                      <td style={td}>Leave conflict</td>
                      <td style={td}><Link to={`/employees/${c.employeeId}`} style={{ color: colors.select }}>{c.name}</Link></td>
                      <td style={{ ...td, color: colors.muted }}>{c.date}{c.rawCode ? ` · ${c.rawCode}` : ''}</td>
                    </tr>
                  ))}
                  {quality.unverifiedTop.map((u) => (
                    <tr key={`u-${u.employeeId}`} style={{ borderTop: `1px solid ${colors.line}` }}>
                      <td style={td}>Unverified days</td>
                      <td style={td}><Link to={`/employees/${u.employeeId}`} style={{ color: colors.select }}>{u.name}</Link></td>
                      <td style={{ ...td, color: colors.muted }}>{u.days} day{u.days === 1 ? '' : 's'} in scope</td>
                    </tr>
                  ))}
                  {quality.noLeaveData.slice(0, 10).map((e) => (
                    <tr key={`n-${e.id}`} style={{ borderTop: `1px solid ${colors.line}` }}>
                      <td style={td}>No leave data</td>
                      <td style={td}><Link to={`/employees/${e.id}`} style={{ color: colors.select }}>{e.name}</Link></td>
                      <td style={{ ...td, color: colors.muted }}>In scope but in no covering import</td>
                    </tr>
                  ))}
                  {quality.noLeaveData.length > 10 && (
                    <tr style={{ borderTop: `1px solid ${colors.line}` }}>
                      <td style={td}>No leave data</td><td style={td}>…</td>
                      <td style={{ ...td, color: colors.muted }}>{quality.noLeaveData.length - 10} more</td>
                    </tr>
                  )}
                  {quality.disagreements.map((c, i) => (
                    <tr key={`d-${i}`} style={{ borderTop: `1px solid ${colors.line}` }}>
                      <td style={td}>Zoho-absent punch</td>
                      <td style={td}><Link to={`/employees/${c.employeeId}`} style={{ color: colors.select }}>{c.name}</Link></td>
                      <td style={{ ...td, color: colors.muted }}>{c.date}{c.rawCode ? ` · ${c.rawCode}` : ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      <section>
        <h3 style={{ fontSize: 15, fontWeight: 600, margin: '0 0 12px' }}>Sync log</h3>
        <div style={{ border: `1px solid ${colors.line}`, borderRadius: 4, overflow: 'hidden', background: colors.panel }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr><th style={th}>Source</th><th style={th}>Ran at</th><th style={thR}>Processed</th><th style={thR}>Failed</th><th style={th}>Status</th><th style={th}>Notes</th></tr></thead>
            <tbody>
              {(coverage?.sync_log ?? []).map((s, i) => (
                <tr key={s.id} style={{ borderTop: `1px solid ${colors.line}`, background: i % 2 ? 'rgba(0,0,0,0.015)' : 'transparent' }}>
                  <td style={{ ...td, fontFamily: "'IBM Plex Mono', monospace", fontSize: 12 }}>{s.source}</td>
                  <td style={{ ...td, color: colors.muted, fontSize: 12.5 }}>{nairobi(s.run_at)}</td>
                  <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{s.records_processed}</td>
                  <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace", color: s.records_failed > 0 ? colors.alert : colors.ink }}>{s.records_failed}</td>
                  <td style={{ ...td, color: s.status === 'complete' ? colors.good : colors.alert, fontWeight: 500 }}>{s.status}</td>
                  <td style={{ ...td, fontSize: 12.5, color: colors.muted }}>{s.notes || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
