// Data health (#/data-health): renamed Sync check + summary card (§6.6).
import React from 'react';
import { Link } from 'react-router-dom';
import { colors } from '../theme.js';
import { isWeekendISO, shortDateISO } from '../metrics.js';
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
  const { coverage, agg, update } = scope;
  const last = coverage?.sync_log?.[0];
  const lastAgeH = last ? (Date.now() - new Date(last.run_at).getTime()) / 3600000 : null;
  const ageTone = lastAgeH === null ? colors.muted : lastAgeH > 72 ? colors.alert : lastAgeH > 24 ? '#c58a1b' : colors.good;

  const counts = (coverage?.per_date ?? []).map((d) => d.count).sort((a, b) => a - b);
  const typical = counts.length ? counts[Math.floor(counts.length / 2)] : 0;

  return (
    <>
      <h2 style={{ fontSize: 16, fontWeight: 600, margin: '0 0 14px' }}>Data health</h2>
      <section style={{ display: 'flex', flexWrap: 'wrap', gap: 0, marginBottom: 24, border: `1px solid ${colors.line}`, borderRadius: 4, overflow: 'hidden', background: colors.panel }}>
        {[
          ['Last sync', last ? `${nairobi(last.run_at)} (${age(last.run_at)})` : '—', ageTone],
          ['Data range', coverage?.date_min && coverage?.date_max ? `${coverage.date_min} – ${coverage.date_max}` : '—'],
          ['Rows / employees', coverage ? `${coverage.attendance_rows} / ${coverage.employees}` : '—'],
          ['Leave data', (coverage?.leave_by_month ?? []).length ? `Loaded (${(coverage.leave_by_month).join(', ')})` : 'Not loaded'],
          ['No punches (filter)', agg.neverPunchedCount, undefined, '/employees?group=nopunch'],
        ].map(([label, value, tone, to], i) => (
          <div key={label} style={{ flex: '1 1 200px', padding: '14px 16px', borderRight: `1px solid ${colors.line}` }}>
            <div style={{ fontSize: 12, color: colors.muted, marginBottom: 6 }}>{label}</div>
            <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 16, color: tone || colors.ink }}>
              {to ? <Link to={to} style={{ color: colors.select }}>{value}</Link> : value}
            </div>
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
            const c = empty ? colors.alert : thin ? '#c58a1b' : colors.good;
            return (
              <div key={d.date} title={`${d.date} — ${d.count} rows (typical: ${typical})`}
                style={{
                  padding: '6px 10px', borderRadius: 20, fontSize: 12, fontFamily: "'IBM Plex Mono', monospace",
                  background: weekend && !thin && !empty ? colors.paper : `${c}1F`,
                  color: weekend && !thin && !empty ? colors.muted : c,
                  border: weekend && !thin && !empty ? `1px dashed ${colors.line}` : `1px solid ${c}4D`,
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
