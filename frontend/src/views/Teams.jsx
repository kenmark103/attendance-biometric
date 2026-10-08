// Teams (#/teams) and Team detail (#/teams/:teamSlug).
import React, { useMemo } from 'react';
import { Link, useParams } from 'react-router-dom';
import { colors } from '../theme.js';
import { formatPct, statusLabel, teamSlug, classifyDay } from '../metrics.js';
import { scopeCaption } from '../filters.js';
import { LeaveBanner, scopeCaptionLine } from '../Dashboard.jsx';
import { RateLine, Sparkline } from '../components/Charts.jsx';
import AttendanceHeatmap from '../components/Heatmap.jsx';
import { EmptyChart } from './Overview.jsx';

const th = { textAlign: 'left', padding: '10px 16px', color: colors.muted, fontWeight: 500, fontSize: 12 };
const thR = { ...th, textAlign: 'right' };
const td = { padding: '9px 16px', fontSize: 13 };

function teamAgg(employees) {
  const m = {};
  for (const e of employees) {
    if (!m[e.team]) m[e.team] = { team: e.team, headcount: 0, present: 0, expected: 0, noRecord: 0 };
    m[e.team].headcount += 1;
    m[e.team].present += e.present;
    m[e.team].expected += e.expected;
    m[e.team].noRecord += e.noRecord;
  }
  return Object.values(m).map((t) => ({
    ...t,
    rate: t.expected ? t.present / t.expected : null,
    noRecordRate: t.expected ? t.noRecord / t.expected : null,
    small: t.headcount < 5,
  }));
}

function teamDaily(rows, team, dates, ctx) {
  return dates.map((d) => {
    const day = rows.filter((r) => r.date === d && r.team === team);
    const ids = new Set(day.map((r) => r.employeeId));
    let present = 0, expected = 0;
    // employees with rows that day + teammates with none (no_record if working past day)
    const mates = rows.filter((r) => r.team === team).map((r) => r.employeeId);
    const allIds = [...new Set(mates)];
    const byId = new Map(day.map((r) => [r.employeeId, r]));
    for (const id of allIds) {
      const st = classifyDay(byId.get(id) || { date: d, leaves: [] }, ctx);
      if (st === 'present' || st === 'missing_checkout') present += 1;
      if (st === 'present' || st === 'missing_checkout' || st === 'no_record') expected += 1;
    }
    return { date: d, label: d.slice(8, 10), rate: expected ? Math.round((present / expected) * 1000) / 10 : null };
  });
}

export default function Teams({ scope }) {
  const { agg, filters, slugToName, teamNames, leaveLoaded, update } = scope;
  const stats = useMemo(() => teamAgg(agg.employees), [agg.employees]);
  const selectedSlugs = filters.teams; // null = all
  const noRecordLabel = statusLabel('no_record', leaveLoaded);

  const sort = filters.sort || 'rate:asc';
  const [sortKey, sortDir] = sort.split(':');
  const visible = stats.filter((t) => !selectedSlugs || selectedSlugs.includes(teamSlug(t.team)));
  const hidden = stats.filter((t) => selectedSlugs && !selectedSlugs.includes(teamSlug(t.team)));
  visible.sort((a, b) => {
    const av = sortKey === 'team' ? a.team : sortKey === 'headcount' ? a.headcount : sortKey === 'noRecordRate' ? (a.noRecordRate ?? -1) : (a.rate ?? -1);
    const bv = sortKey === 'team' ? b.team : sortKey === 'headcount' ? b.headcount : sortKey === 'noRecordRate' ? (b.noRecordRate ?? -1) : (b.rate ?? -1);
    const cmp = typeof av === 'string' ? av.localeCompare(bv) : av - bv;
    return sortDir === 'asc' ? cmp : -cmp;
  });

  function toggleSort(key) {
    update({ sort: sortKey === key && sortDir === 'asc' ? `${key}:desc` : `${key}:asc` });
  }
  function toggleTeam(name) {
    const slug = teamSlug(name);
    const cur = selectedSlugs || teamNames.map(teamSlug);
    const next = cur.includes(slug) ? cur.filter((s) => s !== slug) : [...cur, slug];
    if (!next.length) return;
    update({ teams: next.length === teamNames.length ? null : next });
  }

  const sortMark = (k) => (sortKey === k ? (sortDir === 'asc' ? ' ↑' : ' ↓') : '');
  const rows = filters.allteams ? [...visible, ...hidden] : visible;

  return (
    <>
      {!leaveLoaded && <LeaveBanner />}
      <h2 style={{ fontSize: 16, fontWeight: 600, margin: '0 0 14px' }}>Attendance by team</h2>
      {agg.employees.length === 0 ? (
        <EmptyState scope={scope} />
      ) : (
        <div style={{ border: `1px solid ${colors.line}`, borderRadius: 4, overflow: 'hidden', background: colors.panel }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr>
              <th style={th}>Include</th>
              <th style={{ ...th, cursor: 'pointer' }} onClick={() => toggleSort('team')}>Team{sortMark('team')}</th>
              <th style={{ ...thR, cursor: 'pointer' }} onClick={() => toggleSort('headcount')}>Headcount{sortMark('headcount')}</th>
              <th style={{ ...thR, cursor: 'pointer' }} onClick={() => toggleSort('rate')}>Attendance rate{sortMark('rate')}</th>
              <th style={{ ...thR, cursor: 'pointer' }} onClick={() => toggleSort('noRecordRate')}>{noRecordLabel} rate{sortMark('noRecordRate')}</th>
              <th style={thR}>Trend</th>
            </tr></thead>
            <tbody>
              {rows.map((t, i) => {
                const slug = teamSlug(t.team);
                const included = !selectedSlugs || selectedSlugs.includes(slug);
                const spark = teamDaily(scope.rows, t.team, scope.scopeDates, scope.ctx).map((d) => d.rate);
                return (
                  <tr key={t.team} style={{
                    borderTop: `1px solid ${colors.line}`, cursor: 'pointer',
                    opacity: included ? 1 : 0.55,
                    background: i % 2 ? 'rgba(0,0,0,0.015)' : 'transparent',
                  }}
                    onClick={() => scope.switchTab(`/teams/${slug}`)}>
                    <td style={td} onClick={(e) => e.stopPropagation()}>
                      <input type="checkbox" checked={included} onChange={() => toggleTeam(t.team)} aria-label={`Include ${t.team}`} />
                    </td>
                    <td style={{ ...td, fontWeight: 500, color: colors.select }}>{t.team}</td>
                    <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{t.headcount}</td>
                    <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace", color: t.rate !== null && t.rate < 0.6 ? colors.alert : colors.ink }}>
                      {formatPct(t.rate)}
                      {t.small && <span title="Small team: rates move a lot with one person" style={{ color: colors.muted, fontSize: 11, marginLeft: 6 }}>n={t.headcount}</span>}
                    </td>
                    <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{formatPct(t.noRecordRate)}</td>
                    <td style={{ ...td, textAlign: 'right' }}>
                      <Sparkline values={spark} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <div style={{ fontSize: 12, color: colors.muted, marginTop: 10 }}>
        Tick the checkbox to include a team in every view. Click a team to drill down.{' '}
        {selectedSlugs && !filters.allteams && hidden.length > 0 && (
          <button onClick={() => update({ allteams: true })} style={{ background: 'none', border: 'none', color: colors.select, cursor: 'pointer', fontSize: 12 }}>
            Show all teams ({hidden.length} hidden)
          </button>
        )}
        {filters.allteams && (
          <button onClick={() => update({ allteams: false })} style={{ background: 'none', border: 'none', color: colors.select, cursor: 'pointer', fontSize: 12 }}>
            Show selected only
          </button>
        )}
      </div>
    </>
  );
}

export function EmptyState({ scope }) {
  return (
    <div style={{ border: `1px solid ${colors.line}`, borderRadius: 4, background: colors.panel, padding: 40, textAlign: 'center' }}>
      <div style={{ fontSize: 14, marginBottom: 12 }}>No employees match these filters</div>
      <button onClick={() => scope.update({}, { reset: true })} style={{ fontFamily: 'inherit', fontSize: 13, padding: '7px 14px', cursor: 'pointer', border: `1px solid ${colors.line}`, borderRadius: 20, background: colors.panel }}>
        Reset filters
      </button>
    </div>
  );
}

export function TeamDetail({ scope }) {
  const { teamSlug: slug } = useParams();
  const { agg, scopeDates, rows, ctx, slugToName, filters, leaveLoaded } = scope;
  const name = slugToName.get(slug);
  if (!name) {
    return (
      <div style={{ border: `1px solid ${colors.line}`, borderRadius: 4, background: colors.panel, padding: 40, textAlign: 'center' }}>
        <div style={{ fontSize: 14, marginBottom: 12 }}>Team not found</div>
        <Link to="/teams" style={{ color: colors.select }}>Back to Teams</Link>
      </div>
    );
  }
  const members = agg.employees.filter((e) => e.team === name);
  const teamRows = rows.filter((r) => r.team === name);
  const daily = teamDaily(rows, name, scopeDates, ctx).map((d, i) => ({ ...d, label: scope.scopeDates[i] ? scope.scopeDates[i].slice(5) : d.label }));
  const expected = members.reduce((s, e) => s + e.expected, 0);
  const present = members.reduce((s, e) => s + e.present, 0);
  return (
    <>
      {!leaveLoaded && <LeaveBanner />}
      <div style={{ fontSize: 13, color: colors.muted, marginBottom: 8 }}>
        <Link to="/teams" style={{ color: colors.select }}>Teams</Link> / <strong style={{ color: colors.ink }}>{name}</strong>
      </div>
      <section style={{ display: 'flex', flexWrap: 'wrap', gap: 0, marginBottom: 24, border: `1px solid ${colors.line}`, borderRadius: 4, overflow: 'hidden', background: colors.panel }}>
        {[
          ['Headcount', members.length],
          ['Attendance rate', formatPct(expected ? present / expected : null)],
          ['No record', members.reduce((s, e) => s + e.noRecord, 0)],
        ].map(([label, value], i) => (
          <div key={label} style={{ flex: '1 1 160px', padding: '18px 20px', borderRight: i < 2 ? `1px solid ${colors.line}` : 'none' }}>
            <div style={{ fontSize: 12, color: colors.muted, marginBottom: 8 }}>{label}</div>
            <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 24 }}>{value}</div>
          </div>
        ))}
      </section>
      <section style={{ marginBottom: 24 }}>
        <h3 style={{ fontSize: 15, fontWeight: 600, margin: '0 0 12px' }}>Attendance rate by day</h3>
        <div style={{ background: colors.panel, border: `1px solid ${colors.line}`, borderRadius: 4, padding: '16px 20px 4px' }}>
          <RateLine data={daily} />
        </div>
      </section>
      <section style={{ marginBottom: 24 }}>
        <h3 style={{ fontSize: 15, fontWeight: 600, margin: '0 0 12px' }}>Members</h3>
        <AttendanceHeatmap employees={members} rows={teamRows} dates={scopeDates} ctx={ctx} scope={scope} />
      </section>
      <section>
        <h3 style={{ fontSize: 15, fontWeight: 600, margin: '0 0 12px' }}>Member table</h3>
        <MemberTable members={members} scope={scope} />
      </section>
    </>
  );
}

export function MemberTable({ members, scope }) {
  const noRecordLabel = statusLabel('no_record', scope.leaveLoaded);
  const sorted = [...members].sort((a, b) => b.noRecord - a.noRecord || a.name.localeCompare(b.name));
  return (
    <div style={{ border: `1px solid ${colors.line}`, borderRadius: 4, overflow: 'hidden', background: colors.panel }}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead><tr>
          <th style={th}>Name</th><th style={th}>Team</th>
          <th style={thR}>Present</th><th style={thR}>On leave</th><th style={thR}>{noRecordLabel}</th>
          <th style={thR}>Avg hrs/day</th>
        </tr></thead>
        <tbody>
          {sorted.map((e, i) => (
            <tr key={e.id} style={{ borderTop: `1px solid ${colors.line}`, background: i % 2 ? 'rgba(0,0,0,0.015)' : 'transparent' }}>
              <td style={{ ...td, fontWeight: 500 }}>
                <Link to={`/employees/${e.id}`} style={{ color: colors.select, textDecoration: 'none' }}>{e.name}</Link>
                <span style={{ color: colors.muted, fontFamily: "'IBM Plex Mono', monospace", fontSize: 11.5, marginLeft: 8 }}>{e.id}</span>
              </td>
              <td style={{ ...td, fontSize: 12.5 }}>{e.team}</td>
              <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{e.present} / {e.expected}</td>
              <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace", color: colors.warn }}>{e.leave || '—'}</td>
              <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{e.noRecord || '—'}</td>
              <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{e.avgHours || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
