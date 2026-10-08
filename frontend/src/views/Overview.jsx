// Overview (#/): KPI strip, daily rate line, stacked breakdown, attention panels.
import React from 'react';
import { Link } from 'react-router-dom';
import { colors } from '../theme.js';
import { formatPct, statusLabel, kpiLabels } from '../metrics.js';
import { scopeCaption } from '../filters.js';
import { LeaveBanner, scopeCaptionLine } from '../Dashboard.jsx';
import { RateLine, BreakdownBars, ChartLegend } from '../components/Charts.jsx';

function Card({ label, value, tone, to, title }) {
  const inner = (
    <div style={{ padding: '18px 20px' }}>
      <div style={{ fontSize: 12, color: colors.muted, marginBottom: 8 }}>{label}</div>
      <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 24, fontWeight: 500, color: tone || colors.ink }}>{value}</div>
    </div>
  );
  if (!to) return <div style={{ flex: '1 1 160px', borderRight: `1px solid ${colors.line}` }}>{inner}</div>;
  return (
    <Link to={to} title={title} style={{ flex: '1 1 160px', borderRight: `1px solid ${colors.line}`, textDecoration: 'none' }}>
      {inner}
    </Link>
  );
}

export default function Overview({ scope }) {
  const { agg, daily, filters, slugToName, leaveLoaded, today } = scope;
  const labels = kpiLabels(leaveLoaded);
  const noRecordLabel = statusLabel('no_record', leaveLoaded);
  const distinctSources = [...new Set(scope.rows.map((r) => r.source || 'migrated'))];

  const lineData = daily.map((d) => ({ ...d, rate: d.rate }));
  const barData = daily.map((d) => ({
    ...d,
    present: d.present,
    leave: d.leave,
    noRecord: d.noRecord,
    inProgress: d.inProg,
  }));

  const rangeHasToday = scope.scopeDates.includes(today);
  const captionExtra = filters.shift !== 'all' ? `${filters.shift} shift` : '';

  // Needs attention
  const byTeam = {};
  for (const e of agg.employees) {
    if (!byTeam[e.team]) byTeam[e.team] = { team: e.team, headcount: 0, present: 0, expected: 0 };
    byTeam[e.team].headcount += 1;
    byTeam[e.team].present += e.present;
    byTeam[e.team].expected += e.expected;
  }
  const lowTeams = Object.values(byTeam)
    .filter((t) => t.headcount >= 3 && t.expected > 0)
    .map((t) => ({ ...t, rate: t.present / t.expected }))
    .sort((a, b) => a.rate - b.rate)
    .slice(0, 5);
  const neverIds = new Set(agg.employees.filter((e) => e.neverPunched).map((e) => e.id));
  const mostNoRecord = agg.employees
    .filter((e) => !e.neverPunched && e.noRecord > 0)
    .sort((a, b) => b.noRecord - a.noRecord || a.name.localeCompare(b.name))
    .slice(0, 8);

  const teamSlugOf = (name) => [...slugToName.entries()].find(([, n]) => n === name)?.[0] || '';

  return (
    <>
      {!leaveLoaded && <LeaveBanner />}
      <section style={{ display: 'flex', flexWrap: 'wrap', gap: 0, marginBottom: 8, border: `1px solid ${colors.line}`, borderRadius: 4, overflow: 'hidden', background: colors.panel }}>
        <Card label="Headcount" value={agg.headcount} />
        <Card label="Attendance rate" value={formatPct(agg.attendanceRate)} tone={agg.attendanceRate !== null && agg.attendanceRate < 0.6 ? colors.alert : undefined} />
        <Card label="Avg hours / present day" value={agg.avgHours === null ? '—' : `${agg.avgHours.toFixed(1)}h`} />
        <Card label={labels.count} value={agg.noRecordDays} tone={agg.noRecordDays > 0 ? colors.alert : colors.good} to={`/exceptions?type=no_record`} title="Open filtered exceptions" />
        <Card label="Missing check-outs" value={agg.employees.reduce((s, e) => s + e.missing, 0)} tone={colors.warn} to="/exceptions?type=missing_checkout" title="Open filtered exceptions" />
        <Card label="Off-shift anomalies" value={agg.employees.reduce((s, e) => s + e.offshift, 0)} tone={colors.anomaly} to="/exceptions?type=off_shift" title="Open filtered exceptions" />
        <Card label="No punches in period" value={agg.neverPunchedCount} to="/employees?group=nopunch" title="Open the no-punches group" />
        {distinctSources.length > 1 && (
          <Card label="Verified (biometric) share" value={agg.presentDays ? formatPct(agg.biometricDays / agg.presentDays) : '—'} />
        )}
      </section>
      {scopeCaptionLine(scopeCaption(filters, slugToName), captionExtra)}
      {rangeHasToday && (
        <div style={{ fontSize: 12, color: colors.muted, margin: '-16px 0 24px' }}>Today is shown as in progress and excluded from rates.</div>
      )}

      <section style={{ marginBottom: 36 }}>
        <h2 style={{ fontSize: 16, fontWeight: 600, margin: '0 0 14px' }}>Attendance rate by day</h2>
        <div style={{ background: colors.panel, border: `1px solid ${colors.line}`, borderRadius: 4, padding: '16px 20px 4px' }}>
          {daily.length === 0 ? (
            <EmptyChart text="No attendance data for this month yet." />
          ) : (
            <RateLine data={lineData} />
          )}
        </div>
      </section>

      <section style={{ marginBottom: 36 }}>
        <h2 style={{ fontSize: 16, fontWeight: 600, margin: '0 0 14px' }}>Daily breakdown</h2>
        <div style={{ background: colors.panel, border: `1px solid ${colors.line}`, borderRadius: 4, padding: '16px 20px 4px' }}>
          {daily.length === 0 ? (
            <EmptyChart text="No attendance data for this month yet." />
          ) : (
            <BreakdownBars data={barData} showLeave={leaveLoaded} showInProgress />
          )}
        </div>
        <ChartLegend items={[
          ['Present', colors.good],
          ...(leaveLoaded ? [['On leave', '#3b6ea5']] : []),
          [noRecordLabel, colors.alert],
          ['In progress', `${colors.good}59`, true],
        ]} />
      </section>

      <section style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 320px', background: colors.panel, border: `1px solid ${colors.line}`, borderRadius: 4, padding: '14px 16px' }}>
          <h3 style={{ fontSize: 14, fontWeight: 600, margin: '0 0 10px' }}>Lowest attendance teams</h3>
          {lowTeams.length === 0 && <div style={{ fontSize: 13, color: colors.muted }}>Nothing to flag in this view.</div>}
          {lowTeams.map((t) => (
            <div key={t.team} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, padding: '6px 0', borderTop: `1px solid ${colors.line}` }}>
              <Link to={`/teams/${teamSlugOf(t.team)}`} style={{ color: colors.select }}>{t.team}</Link>
              <span style={{ fontFamily: "'IBM Plex Mono', monospace" }}>{formatPct(t.rate)}</span>
            </div>
          ))}
        </div>
        <div style={{ flex: '1 1 320px', background: colors.panel, border: `1px solid ${colors.line}`, borderRadius: 4, padding: '14px 16px' }}>
          <h3 style={{ fontSize: 14, fontWeight: 600, margin: '0 0 10px' }}>Most {noRecordLabel.toLowerCase()} days</h3>
          {mostNoRecord.length === 0 && <div style={{ fontSize: 13, color: colors.muted }}>Nothing to flag in this view.</div>}
          {mostNoRecord.map((e) => (
            <div key={e.id} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, padding: '6px 0', borderTop: `1px solid ${colors.line}` }}>
              <Link to={`/employees/${e.id}`} style={{ color: colors.select }}>{e.name}</Link>
              <span style={{ fontFamily: "'IBM Plex Mono', monospace" }}>{e.noRecord}</span>
            </div>
          ))}
        </div>
      </section>
    </>
  );
}

export function EmptyChart({ text }) {
  return <div style={{ padding: 40, textAlign: 'center', color: colors.muted, fontSize: 13 }}>{text}</div>;
}
