// Teams (#/teams) and Team detail (#/teams/:teamSlug).
// All rates/statuses come from the API (/dashboard/metrics); this file only
// renders them. The heatmap still classifies days for colouring (spec deviation).
import React from 'react';
import { Link, useParams } from 'react-router-dom';
import { colors } from '../theme.js';
import { formatPct, statusLabel, teamSlug, isWeekendISO } from '../metrics.js';
import { LeaveBanner } from '../Dashboard.jsx';
import { RateLine, Sparkline } from '../components/Charts.jsx';
import AttendanceHeatmap from '../components/Heatmap.jsx';
import { EmptyChart } from './Overview.jsx';

const th = { textAlign: 'left', padding: '10px 16px', color: colors.muted, fontWeight: 500, fontSize: 12 };
const thR = { ...th, textAlign: 'right' };
const td = { padding: '9px 16px', fontSize: 13 };

const noRecordDays = (t) => (t.absent_days || 0) + (t.unverified_days || 0);

function dailyRates(t) {
  return (t.daily || []).map((d) => (d.attendance_rate === null || d.attendance_rate === undefined
    ? null : Math.round(d.attendance_rate * 1000) / 10));
}

export default function Teams({ scope }) {
  const { agg, filters, teamNames, leaveLoaded, leaveActive, update, daily } = scope;
  const stats = scope.apiTeams || [];
  const selectedSlugs = filters.teams; // null = all
  const noRecordLabel = statusLabel('no_record', leaveLoaded);
  const noDataDates = new Set((daily || []).filter((d) => d.state === 'no_data').map((d) => d.date));

  const includedSlugs = selectedSlugs || teamNames.map(teamSlug);
  const includedNames = [...teamNames].filter((n) => includedSlugs.includes(teamSlug(n)));

  const sort = filters.sort || 'rate:asc';
  const [sortKey, sortDir] = sort.split(':');
  const visible = stats.filter((t) => !selectedSlugs || selectedSlugs.includes(teamSlug(t.team)));
  const hidden = stats.filter((t) => selectedSlugs && !selectedSlugs.includes(teamSlug(t.team)));
  const sortVal = (t, k) => (k === 'team' ? t.team
    : k === 'headcount' ? t.headcount
      : k === 'noRecord' ? noRecordDays(t)
        : (t.rate ?? -1));
  visible.sort((a, b) => {
    const av = sortVal(a, sortKey);
    const bv = sortVal(b, sortKey);
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

  const combinedMembers = agg.employees.filter((e) => includedNames.includes(e.team));
  const combinedRows = (scope.rows || []).filter((r) => includedNames.includes(r.team));
  const teamRates = {};
  for (const t of stats) teamRates[t.team] = formatPct(t.rate);

  return (
    <>
      {!leaveLoaded && !leaveActive && <LeaveBanner />}
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
              <th style={{ ...thR, cursor: 'pointer' }} onClick={() => toggleSort('noRecord')}>{noRecordLabel} days{sortMark('noRecord')}</th>
              <th style={thR}>Trend</th>
              <th style={thR} />
            </tr></thead>
            <tbody>
              {rows.map((t) => {
                const slug = teamSlug(t.team);
                const included = !selectedSlugs || selectedSlugs.includes(slug);
                const open = () => scope.switchTab(`/teams/${slug}`);
                return (
                  <tr key={t.team} tabIndex={0} role="link"
                    aria-label={`Open ${t.team}`}
                    onKeyDown={(ev) => { if (ev.key === 'Enter') { ev.preventDefault(); open(); } }}
                    className="team-row"
                    style={{
                      borderTop: `1px solid ${colors.line}`, cursor: 'pointer',
                      opacity: included ? 1 : 0.55,
                    }}
                    onClick={open}>
                    <td style={td} onClick={(e) => e.stopPropagation()}>
                      <input type="checkbox" checked={included} onChange={() => toggleTeam(t.team)} aria-label={`Include ${t.team}`} />
                    </td>
                    <td style={{ ...td, fontWeight: 500, color: colors.select }}>{t.team}</td>
                    <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{t.headcount}</td>
                    <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace", color: t.rate !== null && t.rate !== undefined && t.rate < 0.6 ? colors.alert : colors.ink }}>
                      {formatPct(t.rate)}
                      {t.small && <span title="Small team: rates move a lot with one person" style={{ color: colors.muted, fontSize: 11, marginLeft: 6 }}>n={t.headcount}</span>}
                    </td>
                    <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{noRecordDays(t)}</td>
                    <td style={{ ...td, textAlign: 'right' }}>
                      <Sparkline values={dailyRates(t)} />
                    </td>
                    <td style={{ ...td, textAlign: 'right', color: colors.muted }} aria-hidden="true">›</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <div style={{ fontSize: 12, color: colors.muted, marginTop: 10 }}>
        Click a row to drill down. Tick the checkbox to include a team in every view.{' '}
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

      <section style={{ marginTop: 28 }}>
        <h2 style={{ fontSize: 16, fontWeight: 600, margin: '0 0 14px' }}>Selected teams</h2>
        {combinedMembers.length === 0 ? (
          <div style={{ border: `1px solid ${colors.line}`, borderRadius: 4, background: colors.panel, padding: 32, textAlign: 'center', fontSize: 13, color: colors.muted }}>
            No teams selected
          </div>
        ) : (
          <div style={combinedMembers.length > 150 ? { maxHeight: 560, overflowY: 'auto' } : undefined}>
            <AttendanceHeatmap
              employees={combinedMembers}
              rows={combinedRows}
              dates={scope.scopeDates}
              ctx={scope.ctx}
              scope={scope}
              groupByTeam
              noDataDates={noDataDates}
              teamRates={teamRates}
            />
          </div>
        )}
      </section>
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
  const { agg, scopeDates, rows, ctx, slugToName, leaveLoaded, leaveActive, daily } = scope;
  const name = slugToName.get(slug);
  if (!name) {
    return (
      <div style={{ border: `1px solid ${colors.line}`, borderRadius: 4, background: colors.panel, padding: 40, textAlign: 'center' }}>
        <div style={{ fontSize: 14, marginBottom: 12 }}>Team not found</div>
        <Link to="/teams" style={{ color: colors.select }}>Back to Teams</Link>
      </div>
    );
  }
  const team = (scope.apiTeams || []).find((t) => t.team === name) || { team: name };
  const members = agg.employees.filter((e) => e.team === name);
  const teamRows = rows.filter((r) => r.team === name);
  const through = scope.coverage?.leave_coverage?.through_date || null;
  const chart = (team.daily || []).map((d) => {
    const rate = d.attendance_rate === null || d.attendance_rate === undefined
      ? null : Math.round(d.attendance_rate * 1000) / 10;
    const state = rate === null ? 'no_data'
      : (through && d.date > through ? 'provisional' : 'covered');
    return { date: d.date, label: d.date.slice(5), rate, state };
  }).filter((d) => !isWeekendISO(d.date));
  const noDataDates = new Set((daily || []).filter((d) => d.state === 'no_data').map((d) => d.date));
  const cards = [
    ['Headcount', team.headcount ?? members.length],
    ['Attendance rate', formatPct(team.attendance_rate ?? null)],
    ['No record days', noRecordDays(team)],
  ];
  return (
    <>
      {!leaveLoaded && !leaveActive && <LeaveBanner />}
      <div style={{ fontSize: 13, color: colors.muted, marginBottom: 8 }}>
        <Link to="/teams" style={{ color: colors.select }}>Teams</Link> / <strong style={{ color: colors.ink }}>{name}</strong>
      </div>
      <section style={{ display: 'flex', flexWrap: 'wrap', gap: 0, marginBottom: 24, border: `1px solid ${colors.line}`, borderRadius: 4, overflow: 'hidden', background: colors.panel }}>
        {cards.map(([label, value], i) => (
          <div key={label} style={{ flex: '1 1 160px', padding: '18px 20px', borderRight: i < cards.length - 1 ? `1px solid ${colors.line}` : 'none' }}>
            <div style={{ fontSize: 12, color: colors.muted, marginBottom: 8 }}>{label}</div>
            <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 24 }}>{value}</div>
            {label === 'Attendance rate' && team.is_provisional && (
              <div style={{ fontSize: 11.5, color: colors.muted, marginTop: 6 }}>
                Provisional: {team.provisional_days} day{team.provisional_days === 1 ? '' : 's'} not yet covered by leave data
              </div>
            )}
          </div>
        ))}
      </section>
      <section style={{ marginBottom: 24 }}>
        <h3 style={{ fontSize: 15, fontWeight: 600, margin: '0 0 12px' }}>Attendance rate by day</h3>
        <div style={{ background: colors.panel, border: `1px solid ${colors.line}`, borderRadius: 4, padding: '16px 20px 4px' }}>
          {chart.length === 0 ? <EmptyChart text="No working days in this range yet." /> : <RateLine data={chart} />}
        </div>
      </section>
      <section style={{ marginBottom: 24 }}>
        <h3 style={{ fontSize: 15, fontWeight: 600, margin: '0 0 12px' }}>Members</h3>
        <AttendanceHeatmap employees={members} rows={teamRows} dates={scopeDates} ctx={ctx} scope={scope} noDataDates={noDataDates} />
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
