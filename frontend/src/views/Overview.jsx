// Overview (#/): KPI strip, daily rate line, stacked breakdown, attention panels.
import React from 'react';
import { Link } from 'react-router-dom';
import { colors } from '../theme.js';
import { formatPct, statusLabel } from '../metrics.js';
import { scopeCaption } from '../filters.js';
import { LeaveBanner, scopeCaptionLine } from '../Dashboard.jsx';
import { RateLine, BreakdownBars, ChartLegend } from '../components/Charts.jsx';
import StatusLegend from '../components/StatusLegend.jsx';
import { LEGACY_LEGEND, OVERLAY_LEGEND } from '../statusColors.js';

function Card({ label, value, tone, to, title, sub }) {
  const inner = (
    <div style={{ padding: '18px 20px' }}>
      <div style={{ fontSize: 12, color: colors.muted, marginBottom: 8 }}>{label}</div>
      <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 24, fontWeight: 500, color: tone || colors.ink }}>{value}</div>
      {sub && <div style={{ fontSize: 11.5, color: colors.muted, marginTop: 6 }}>{sub}</div>}
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
  const { agg, daily, filters, slugToName, leaveLoaded, leaveActive, coverage, today } = scope;
  const reconciled = leaveLoaded || leaveActive;
  const noRecordLabel = statusLabel('no_record', reconciled);
  const through = coverage?.leave_coverage?.through_date || null;
  const staleDays = through
    ? Math.floor((Date.now() - new Date(through + 'T00:00:00Z').getTime()) / 86400000)
    : null;

  // Charts skip weekends: they are always all-zero (no expected shift),
  // so they only break the line and pad the bars.
  const chartDays = daily.filter((d) => !d.weekend);
  const lineData = chartDays.map((d) => ({
    ...d,
    prov: d.state === 'provisional' ? d.rate : null,
  }));
  const barData = chartDays.map((d) => ({
    ...d,
    present: d.present,
    leave: d.leave,
    noRecord: d.noRecord,
    absent: d.absent,
    unverified: d.unverified,
    inProgress: d.inProgress,
  }));

  const rangeHasToday = scope.scopeDates.includes(today);
  const captionExtra = filters.shift !== 'all' ? `${filters.shift} shift` : '';

  // Needs attention. Team + employee rates come from the API; nothing is
  // recomputed here.
  const lowTeams = (scope.apiTeams || [])
    .filter((t) => t.headcount >= 3 && t.rate !== null && t.rate !== undefined)
    .sort((a, b) => a.rate - b.rate)
    .slice(0, 5);
  const mostNoRecord = agg.employees
    .filter((e) => !e.neverPunched && e.noRecord > 0)
    .sort((a, b) => b.noRecord - a.noRecord || a.name.localeCompare(b.name))
    .slice(0, 8);

  const teamSlugOf = (name) => [...slugToName.entries()].find(([, n]) => n === name)?.[0] || '';

  return (
    <>
      {!reconciled && <LeaveBanner />}
      {leaveActive && (
        <div style={{
          border: `1px solid ${staleDays !== null && staleDays > 10 ? '#c58a1b' : colors.line}`,
          background: staleDays !== null && staleDays > 10 ? '#fbf3dc' : colors.panel,
          borderRadius: 4, padding: '9px 14px', fontSize: 13, marginBottom: 16, color: colors.ink,
        }}>
          Leave data current through <strong>{through}</strong>
          {staleDays !== null && staleDays > 10 && <> — older than 10 days; HR sends the report weekly</>}.
          {' '}Days past coverage are <strong>unverified</strong>, never counted absent.
        </div>
      )}
      <section style={{ display: 'flex', flexWrap: 'wrap', gap: 0, marginBottom: 8, border: `1px solid ${colors.line}`, borderRadius: 4, overflow: 'hidden', background: colors.panel }}>
        <Card label="Headcount" value={agg.headcount} />
        <Card
          label="Attendance rate"
          value={formatPct(agg.attendanceRate)}
          tone={agg.attendanceRate !== null && agg.attendanceRate < 0.6 ? colors.alert : undefined}
          sub={agg.isProvisional
            ? `Provisional: ${agg.provisionalDays} day${agg.provisionalDays === 1 ? '' : 's'} not yet covered by leave data`
            : null}
        />
        <Card label="Avg hours / present day" value={agg.avgHours === null ? '—' : `${Number(agg.avgHours).toFixed(1)}h`} />
        <Card label="Absent (no leave on record)" value={agg.absentDays} tone={agg.absentDays > 0 ? colors.alert : colors.good} title="Verified absences with leave data" />
        <Card label="Unverified days" value={agg.unverifiedDays} tone={agg.unverifiedDays > 0 ? colors.warn : colors.good} title="No punch and no leave data yet" />
        {leaveActive && (
          <Card label="On leave days" value={agg.onLeaveDays} title="Employee-days reconciled as approved leave" />
        )}
        <Card label="Missing check-outs" value={agg.missingCheckouts} tone={colors.warn} to="/exceptions?type=missing_checkout" title="Open filtered exceptions" />
        <Card label="No punches in period" value={agg.neverPunchedCount} to="/employees?group=nopunch" title="Open the no-punches group" />
      </section>
      {scopeCaptionLine(scopeCaption(filters, slugToName), captionExtra)}
      {agg.noDataDays > 0 && (
        <div style={{ fontSize: 12, color: colors.muted, margin: '-16px 0 16px' }}>
          Dates with no biometric data (sync gaps) are excluded: {agg.noDataDays} working day{agg.noDataDays === 1 ? '' : 's'}.
        </div>
      )}
      {rangeHasToday && (
        <div style={{ fontSize: 12, color: colors.muted, margin: '-16px 0 24px' }}>Today is shown as in progress and excluded from rates.</div>
      )}

      <section style={{ marginBottom: 36 }}>
        <h2 style={{ fontSize: 16, fontWeight: 600, margin: '0 0 14px' }}>Attendance rate by day</h2>
        <div style={{ background: colors.panel, border: `1px solid ${colors.line}`, borderRadius: 4, padding: '16px 20px 4px' }}>
          {lineData.length === 0 ? (
            <EmptyChart text="No working days in this range yet." />
          ) : (
            <RateLine data={lineData} />
          )}
        </div>
      </section>

      <section style={{ marginBottom: 36 }}>
        <h2 style={{ fontSize: 16, fontWeight: 600, margin: '0 0 14px' }}>Daily breakdown</h2>
        <div style={{ background: colors.panel, border: `1px solid ${colors.line}`, borderRadius: 4, padding: '16px 20px 4px' }}>
          {barData.length === 0 ? (
            <EmptyChart text="No working days in this range yet." />
          ) : (
            <BreakdownBars data={barData} showLeave={reconciled} showInProgress showOverlay={leaveActive} />
          )}
        </div>
        {leaveActive ? (
          <StatusLegend statuses={[...OVERLAY_LEGEND, 'no_record', 'in_progress']} leaveLoaded={reconciled} />
        ) : (
          <ChartLegend items={[
            ['Present', colors.good],
            ...(reconciled ? [['On leave', '#3b6ea5']] : []),
            [noRecordLabel, colors.alert],
            ['In progress', `${colors.good}59`, true],
          ]} />
        )}
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
