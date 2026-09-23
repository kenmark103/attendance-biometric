import React, { useState, useMemo } from 'react';
import { BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

const DAY_ORDER = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const MONTH_ABBR = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const MONTH_FULL = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

function parseDate(dateStr) {
  return new Date(dateStr + 'T00:00:00');
}
function dayLabel(dateStr) {
  const d = parseDate(dateStr);
  return DAY_ORDER[(d.getDay() + 6) % 7];
}
function isWeekend(dateStr) {
  const dow = parseDate(dateStr).getDay();
  return dow === 0 || dow === 6;
}
function shortDate(dateStr) {
  const d = parseDate(dateStr);
  return `${MONTH_ABBR[d.getMonth()]} ${d.getDate()}`;
}
function monthKey(dateStr) {
  const d = parseDate(dateStr);
  return `${d.getFullYear()}-${d.getMonth()}`;
}
function monthName(dateStr) {
  const d = parseDate(dateStr);
  return `${MONTH_FULL[d.getMonth()]} ${d.getFullYear()}`;
}

// --- status classification -------------------------------------------
// Deliberately no "exempt" bucket reconstructed via guesswork — that field
// doesn't exist in the new schema. Holiday is now a first-class status,
// fed by the real /holidays endpoint instead of being invisible.
function dayStatus(rec) {
  if (rec.present) return 'present';
  if (rec.isHoliday) return 'holiday';
  if (rec.leaves.length > 0) return 'onLeave';
  return 'unauthorized';
}

const colors = {
  ink: '#1C2321', paper: '#F1F3EF', panel: '#FFFFFF', line: '#DBE0D9',
  muted: '#6E786F', good: '#3A6B52', alert: '#A63D2F', warn: '#B98B2E',
  neutral: '#8C8F7E', select: '#2F5D8A', holiday: '#6B5B95', anomaly: '#C97A2B',
};

const STATUS_COLOR = {
  present: colors.good, holiday: colors.holiday, onLeave: colors.warn,
  unauthorized: colors.alert,
};
const STATUS_LABEL = {
  present: 'Present', holiday: 'Public holiday', onLeave: 'On leave',
  unauthorized: 'Absent — no leave on record',
};

// Trust tier: how strong is the evidence behind "present"? Biometric is a
// physical scan; zoho_manual is self-attested; migrated is historical
// import predating this distinction entirely.
const SOURCE_COLOR = { biometric: colors.good, zoho_manual: colors.warn, migrated: colors.neutral };
const SOURCE_LABEL = { biometric: 'Biometric (verified)', zoho_manual: 'Self-reported check-in', migrated: 'Migrated historical data' };

function leaveLabel(rec) {
  if (!rec.leaves.length) return '';
  return rec.leaves.map((l) => l.type).join(', ');
}

function computeDerived(records) {
  const weekdayRecordsAll = records.filter((r) => !isWeekend(r.date));
  const sortedDates = [...new Set(weekdayRecordsAll.map((r) => r.date))].sort();
  const WEEKS = [];
  sortedDates.forEach((date) => {
    const last = WEEKS[WEEKS.length - 1];
    if (last) {
      const prev = parseDate(last.dates[last.dates.length - 1]);
      const cur = parseDate(date);
      const gapDays = Math.round((cur - prev) / 86400000);
      if (gapDays <= 1) {
        last.dates.push(date);
        return;
      }
    }
    WEEKS.push({ dates: [date] });
  });
  WEEKS.forEach((w) => {
    w.start = w.dates[0];
    w.end = w.dates[w.dates.length - 1];
    w.label = `${shortDate(w.start)}\u2013${parseDate(w.end).getDate()}`;
    const counts = {};
    w.dates.forEach((d) => { const k = monthKey(d); counts[k] = (counts[k] || 0) + 1; });
    w.month = Object.entries(counts).sort((a, b) => b[1] - a[1])[0][0];
  });
  const MONTHS = [...new Set(WEEKS.map((w) => w.month))].sort().map((key) => ({
    key, label: monthName(WEEKS.find((w) => w.month === key).dates[0]),
  }));
  const ALL_TEAMS = [...new Set(weekdayRecordsAll.map((r) => r.team))].sort();
  return { weekdayRecordsAll, WEEKS, MONTHS, ALL_TEAMS };
}

function DayChips({ empId, dates, weekdayRecordsAll }) {
  const byDate = {};
  weekdayRecordsAll.forEach((r) => { if (r.employeeId === empId) byDate[r.date] = r; });
  return (
    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', maxWidth: 280 }}>
      {dates.map((date) => {
        const rec = byDate[date];
        const status = rec ? dayStatus(rec) : 'unauthorized';
        const c = STATUS_COLOR[status];
        const label = rec ? (rec.isHoliday ? rec.holidayName : (leaveLabel(rec) || STATUS_LABEL[status])) : 'No record';
        return (
          <div
            key={date}
            title={`${dayLabel(date)} ${shortDate(date)} \u2014 ${label}${rec?.shiftAnomaly ? ' (off-shift)' : ''}`}
            style={{
              width: 22, height: 22, borderRadius: 4, display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 10.5, fontFamily: "'IBM Plex Mono', monospace", fontWeight: 600,
              background: `${c}1F`, color: c, border: rec?.shiftAnomaly ? `1.5px solid ${colors.anomaly}` : `1px solid ${c}4D`,
              flexShrink: 0, position: 'relative',
            }}
          >
            {dayLabel(date)[0]}
          </div>
        );
      })}
    </div>
  );
}

function SourceDot({ source }) {
  const c = SOURCE_COLOR[source] || colors.neutral;
  return (
    <span
      title={SOURCE_LABEL[source] || source}
      style={{ display: 'inline-block', width: 7, height: 7, borderRadius: '50%', background: c, marginLeft: 6 }}
    />
  );
}

const TABS = ['Overview', 'Teams', 'Employees', 'Anomalies & Leave'];

export default function AttendanceDashboard({ records }) {
  const { weekdayRecordsAll, WEEKS, MONTHS, ALL_TEAMS } = useMemo(() => computeDerived(records), [records]);

  const [tab, setTab] = useState('Overview');
  const [team, setTeam] = useState('All teams');
  const [monthFilter, setMonthFilter] = useState('All months');
  const [weekIdx, setWeekIdx] = useState(-1);
  const [query, setQuery] = useState('');
  const [sortKey, setSortKey] = useState('unauthorized');
  const [sortDir, setSortDir] = useState('desc');
  const [selectedEmpId, setSelectedEmpId] = useState(null);

  const teamFiltered = useMemo(() => {
    if (team === 'All teams') return weekdayRecordsAll;
    return weekdayRecordsAll.filter((r) => r.team === team);
  }, [team, weekdayRecordsAll]);

  const visibleWeeks = useMemo(() => {
    if (monthFilter === 'All months') return WEEKS;
    return WEEKS.filter((w) => w.month === monthFilter);
  }, [monthFilter, WEEKS]);

  function handleMonthChange(val) { setMonthFilter(val); setWeekIdx(-1); }
  function handleTeamClick(t) { setTeam(t === team ? 'All teams' : t); }

  const isAggregate = weekIdx === -1 || !visibleWeeks[weekIdx];
  const scopeDates = useMemo(() => {
    if (isAggregate) return visibleWeeks.flatMap((w) => w.dates);
    return visibleWeeks[weekIdx].dates;
  }, [visibleWeeks, weekIdx, isAggregate]);
  const scopeLabel = isAggregate
    ? (monthFilter === 'All months' ? `All ${WEEKS.length} weeks` : monthFilter)
    : visibleWeeks[weekIdx].label;

  const scopeRecords = useMemo(() => {
    const dateSet = new Set(scopeDates);
    return teamFiltered.filter((r) => dateSet.has(r.date));
  }, [teamFiltered, scopeDates]);

  const trendData = useMemo(() => WEEKS.map((w) => {
    const recs = teamFiltered.filter((r) => w.dates.includes(r.date) && dayStatus(r) !== 'holiday');
    const present = recs.filter((r) => r.present).length;
    const unauthorized = recs.filter((r) => dayStatus(r) === 'unauthorized').length;
    const rate = recs.length ? Math.round((present / recs.length) * 1000) / 10 : 0;
    const unauthRate = recs.length ? Math.round((unauthorized / recs.length) * 1000) / 10 : 0;
    return { label: w.label, rate, unauthRate };
  }), [teamFiltered, WEEKS]);

  const chartData = useMemo(() => {
    const bucket = isAggregate ? visibleWeeks : scopeDates.map((d) => ({ dates: [d], label: dayLabel(d) }));
    return bucket.map((b) => {
      const recs = scopeRecords.filter((r) => b.dates.includes(r.date));
      const present = recs.filter((r) => dayStatus(r) === 'present').length;
      const holiday = recs.filter((r) => dayStatus(r) === 'holiday').length;
      const onLeave = recs.filter((r) => dayStatus(r) === 'onLeave').length;
      const unauthorized = recs.filter((r) => dayStatus(r) === 'unauthorized').length;
      return { label: b.label, present, holiday, onLeave, unauthorized, total: recs.length };
    });
  }, [scopeRecords, isAggregate, scopeDates, visibleWeeks]);

  const employeeStats = useMemo(() => {
    const byId = {};
    scopeRecords.forEach((r) => {
      if (!byId[r.employeeId]) {
        byId[r.employeeId] = {
          id: r.employeeId, name: r.name, team: r.team,
          present: 0, holiday: 0, onLeave: 0, unauthorized: 0,
          hours: 0, late: 0, early: 0, overtime: 0,
          biometricDays: 0, anomalyDays: 0,
        };
      }
      const e = byId[r.employeeId];
      const status = dayStatus(r);
      if (status === 'present') {
        e.present += 1; e.hours += r.hours; e.overtime += r.overtime;
        if (r.source === 'biometric') e.biometricDays += 1;
      } else if (status === 'holiday') e.holiday += 1;
      else if (status === 'onLeave') e.onLeave += 1;
      else e.unauthorized += 1;
      if (r.late) e.late += 1;
      if (r.early) e.early += 1;
      if (r.shiftAnomaly) e.anomalyDays += 1;
    });
    return Object.values(byId).map((e) => ({
      ...e,
      absences: e.onLeave + e.unauthorized,
      avgHours: e.present ? Math.round((e.hours / e.present) * 10) / 10 : 0,
    }));
  }, [scopeRecords]);

  const teamStats = useMemo(() => {
    const byTeam = {};
    const dateSet = new Set(scopeDates);
    const base = weekdayRecordsAll.filter((r) => dateSet.has(r.date));
    base.forEach((r) => {
      if (!byTeam[r.team]) byTeam[r.team] = { team: r.team, present: 0, unauthorized: 0, total: 0, ids: new Set() };
      byTeam[r.team].ids.add(r.employeeId);
      const status = dayStatus(r);
      if (status === 'holiday') return;
      byTeam[r.team].total += 1;
      if (r.present) byTeam[r.team].present += 1;
      if (status === 'unauthorized') byTeam[r.team].unauthorized += 1;
    });
    return Object.values(byTeam).map((t) => ({
      team: t.team, headcount: t.ids.size,
      rate: t.total ? Math.round((t.present / t.total) * 1000) / 10 : 0,
      unauthRate: t.total ? Math.round((t.unauthorized / t.total) * 1000) / 10 : 0,
    })).sort((a, b) => a.rate - b.rate);
  }, [scopeDates, weekdayRecordsAll]);

  const totalEmployees = employeeStats.length;
  const totalPresentSlots = employeeStats.reduce((s, e) => s + e.present, 0);
  const totalSlots = employeeStats.reduce((s, e) => s + e.present + e.absences, 0);
  const attendanceRate = totalSlots ? Math.round((totalPresentSlots / totalSlots) * 1000) / 10 : 0;
  const avgHoursAll = employeeStats.reduce((s, e) => s + e.hours, 0) / Math.max(totalPresentSlots, 1);
  const totalUnauthorized = employeeStats.reduce((s, e) => s + e.unauthorized, 0);
  const totalAnomalies = employeeStats.reduce((s, e) => s + e.anomalyDays, 0);
  const verifiedRate = totalPresentSlots
    ? Math.round((employeeStats.reduce((s, e) => s + e.biometricDays, 0) / totalPresentSlots) * 1000) / 10
    : 0;

  const chronicList = useMemo(
    () => employeeStats.filter((e) => e.unauthorized >= 3).sort((a, b) => b.unauthorized - a.unauthorized),
    [employeeStats]
  );

  const anomalyRecords = useMemo(
    () => scopeRecords.filter((r) => r.shiftAnomaly).sort((a, b) => b.date.localeCompare(a.date)),
    [scopeRecords]
  );
  const leaveRecords = useMemo(
    () => scopeRecords.filter((r) => r.leaves.length > 0).sort((a, b) => b.date.localeCompare(a.date)),
    [scopeRecords]
  );

  const filtered = useMemo(() => {
    let rows = employeeStats.filter((e) => e.name.toLowerCase().includes(query.toLowerCase()) || e.id.includes(query));
    rows.sort((a, b) => {
      const av = a[sortKey], bv = b[sortKey];
      const cmp = typeof av === 'string' ? av.localeCompare(bv) : av - bv;
      return sortDir === 'asc' ? cmp : -cmp;
    });
    return rows;
  }, [query, sortKey, sortDir, employeeStats]);

  function toggleSort(key) {
    if (sortKey === key) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    else { setSortKey(key); setSortDir('desc'); }
  }

  const selectStyle = {
    fontFamily: 'inherit', fontSize: 13, padding: '7px 10px', border: `1px solid ${colors.line}`,
    borderRadius: 4, background: colors.panel, color: colors.ink,
  };

  const singleMatch = filtered.length === 1 ? filtered[0] : null;
  const displayedMatch = singleMatch || (selectedEmpId ? employeeStats.find((e) => e.id === selectedEmpId) : null);

  const th = { textAlign: 'left', padding: '10px 16px', color: colors.muted, fontWeight: 500, fontSize: 12 };
  const thR = { ...th, textAlign: 'right' };
  const td = { padding: '9px 16px', fontSize: 13 };

  return (
    <div style={{
      background: colors.paper, color: colors.ink, minHeight: '100%',
      fontFamily: "'IBM Plex Sans', 'Helvetica Neue', Arial, sans-serif",
      padding: '32px 28px 48px', boxSizing: 'border-box',
    }}>
      <div style={{ maxWidth: 1120, margin: '0 auto' }}>

        <header style={{ marginBottom: 20, borderBottom: `1px solid ${colors.line}`, paddingBottom: 20, textAlign: 'center' }}>
          <h1 style={{ fontFamily: "'Fraunces', Georgia, serif", fontWeight: 700, fontSize: 30, margin: 0, lineHeight: 1.2 }}>
            Attendance Dashboard
          </h1>
        </header>

        {/* Tabs */}
        <div style={{ display: 'flex', gap: 4, marginBottom: 20, borderBottom: `1px solid ${colors.line}` }}>
          {TABS.map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              style={{
                fontFamily: 'inherit', fontSize: 13.5, padding: '10px 16px', cursor: 'pointer',
                border: 'none', borderBottom: tab === t ? `2px solid ${colors.select}` : '2px solid transparent',
                background: 'none', color: tab === t ? colors.select : colors.muted,
                fontWeight: tab === t ? 600 : 500,
              }}
            >
              {t}{t === 'Anomalies & Leave' && (totalAnomalies > 0) ? ` (${totalAnomalies})` : ''}
            </button>
          ))}
        </div>

        {/* Shared filters */}
        <section style={{ marginBottom: 20 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12, flexWrap: 'wrap', gap: 10 }}>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {visibleWeeks.map((w) => {
                const idx = WEEKS.indexOf(w);
                return (
                  <button key={w.start} onClick={() => setWeekIdx(idx)} style={{ fontFamily: 'inherit', fontSize: 12.5, padding: '7px 14px', cursor: 'pointer', border: `1px solid ${idx === weekIdx ? colors.ink : colors.line}`, background: idx === weekIdx ? colors.ink : colors.panel, color: idx === weekIdx ? colors.paper : colors.ink, borderRadius: 20 }}>{w.label}</button>
                );
              })}
              <button onClick={() => setWeekIdx(-1)} style={{ fontFamily: 'inherit', fontSize: 12.5, padding: '7px 14px', cursor: 'pointer', fontWeight: 600, border: `1px solid ${isAggregate ? colors.good : colors.line}`, background: isAggregate ? 'rgba(58,107,82,0.1)' : colors.panel, color: isAggregate ? colors.good : colors.ink, borderRadius: 20 }}>{monthFilter === 'All months' ? `All ${WEEKS.length} weeks` : `All of ${monthFilter}`}</button>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <select value={monthFilter} onChange={(e) => handleMonthChange(e.target.value)} style={selectStyle}><option>All months</option>{MONTHS.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}</select>
              <select value={team} onChange={(e) => setTeam(e.target.value)} style={selectStyle}><option>All teams</option>{ALL_TEAMS.map((t) => <option key={t} value={t}>{t}</option>)}</select>
            </div>
          </div>
        </section>

        {tab === 'Overview' && (
          <>
            <section style={{ display: 'flex', flexWrap: 'wrap', gap: 0, marginBottom: 8, border: `1px solid ${colors.line}`, borderRadius: 4, overflow: 'hidden', background: colors.panel }}>
              {[
                { label: 'Headcount', value: totalEmployees, suffix: '' },
                { label: 'Attendance rate', value: attendanceRate, suffix: '%', tone: attendanceRate < 75 ? colors.alert : colors.good },
                { label: 'Verified (biometric) rate', value: verifiedRate, suffix: '%', tone: verifiedRate < 60 ? colors.warn : colors.good },
                { label: 'Avg hours / present day', value: avgHoursAll.toFixed(1), suffix: 'h' },
                { label: 'Unauthorized absences', value: totalUnauthorized, suffix: '', tone: totalUnauthorized > 0 ? colors.alert : colors.good, clickable: true, target: 'chronic' },
                { label: 'Off-shift anomalies', value: totalAnomalies, suffix: '', tone: totalAnomalies > 0 ? colors.anomaly : colors.good, clickable: true, target: 'anomalies' },
              ].map((stat, i) => (
                <div key={i} onClick={stat.clickable ? () => setTab('Anomalies & Leave') : undefined} style={{ flex: '1 1 160px', padding: '18px 20px', borderRight: i < 5 ? `1px solid ${colors.line}` : 'none', cursor: stat.clickable ? 'pointer' : 'default' }}>
                  <div style={{ fontSize: 12, color: colors.muted, marginBottom: 8 }}>{stat.label}{stat.clickable && <span style={{ marginLeft: 5, textDecoration: 'underline dotted' }}>view</span>}</div>
                  <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 24, fontWeight: 500, color: stat.tone || colors.ink }}>{stat.value}{stat.suffix}</div>
                </div>
              ))}
            </section>
            <div style={{ fontSize: 12, color: colors.muted, marginBottom: 32 }}>Figures above reflect: <strong style={{ color: colors.ink }}>{scopeLabel}</strong>{team !== 'All teams' && ` · ${team}`}. Public holidays are excluded from the rate calculations.</div>

            <section style={{ marginBottom: 36 }}>
              <h2 style={{ fontSize: 16, fontWeight: 600, margin: '0 0 14px' }}>Attendance rate, week over week {team !== 'All teams' && <span style={{ color: colors.muted, fontWeight: 400 }}>&middot; {team}</span>}</h2>
              <div style={{ background: colors.panel, border: `1px solid ${colors.line}`, borderRadius: 4, padding: '16px 20px 4px' }}>
                <ResponsiveContainer width="100%" height={200}>
                  <LineChart data={trendData} margin={{ top: 4, right: 16, left: -12, bottom: 4 }}>
                    <CartesianGrid strokeDasharray="2 4" stroke={colors.line} vertical={false} />
                    <XAxis dataKey="label" tick={{ fontSize: 12, fill: colors.muted }} axisLine={{ stroke: colors.line }} tickLine={false} />
                    <YAxis tick={{ fontSize: 12, fill: colors.muted }} axisLine={false} tickLine={false} domain={[0, 100]} />
                    <Tooltip contentStyle={{ border: `1px solid ${colors.line}`, borderRadius: 4, fontSize: 12.5 }} />
                    <Line type="monotone" dataKey="rate" name="Attendance %" stroke={colors.good} strokeWidth={2} dot={{ r: 4, fill: colors.good }} />
                    <Line type="monotone" dataKey="unauthRate" name="Unauthorized %" stroke={colors.alert} strokeWidth={2} dot={{ r: 4, fill: colors.alert }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </section>

            <section>
              <h2 style={{ fontSize: 16, fontWeight: 600, margin: '0 0 14px' }}>{isAggregate ? 'Breakdown by week' : 'Daily breakdown'} <span style={{ color: colors.muted, fontWeight: 400 }}>&middot; {scopeLabel}</span></h2>
              <div style={{ background: colors.panel, border: `1px solid ${colors.line}`, borderRadius: 4, padding: '16px 20px 4px' }}>
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={chartData} margin={{ top: 4, right: 8, left: -12, bottom: 4 }}>
                    <CartesianGrid strokeDasharray="2 4" stroke={colors.line} vertical={false} />
                    <XAxis dataKey="label" tick={{ fontSize: 12, fill: colors.muted }} axisLine={{ stroke: colors.line }} tickLine={false} />
                    <YAxis tick={{ fontSize: 12, fill: colors.muted }} axisLine={false} tickLine={false} />
                    <Tooltip contentStyle={{ border: `1px solid ${colors.line}`, borderRadius: 4, fontSize: 12.5 }} />
                    <Bar dataKey="present" name="Present" stackId="a" fill={colors.good} />
                    <Bar dataKey="holiday" name="Holiday" stackId="a" fill={colors.holiday} />
                    <Bar dataKey="onLeave" name="On leave" stackId="a" fill={colors.warn} />
                    <Bar dataKey="unauthorized" name="No record" stackId="a" fill={colors.alert} radius={[2, 2, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div style={{ display: 'flex', gap: 14, fontSize: 12, color: colors.muted, marginTop: 8, flexWrap: 'wrap' }}>
                {Object.entries(STATUS_LABEL).map(([k, label]) => (
                  <span key={k}><span style={{ display: 'inline-block', width: 9, height: 9, borderRadius: 2, background: STATUS_COLOR[k], marginRight: 5 }} />{label}</span>
                ))}
              </div>
            </section>
          </>
        )}

        {tab === 'Teams' && (
          <section>
            <h2 style={{ fontSize: 16, fontWeight: 600, margin: '0 0 14px' }}>Attendance by team <span style={{ color: colors.muted, fontWeight: 400 }}>&middot; {scopeLabel}</span></h2>
            <div style={{ border: `1px solid ${colors.line}`, borderRadius: 4, overflow: 'hidden', background: colors.panel }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead><tr><th style={th}>Team</th><th style={thR}>Headcount</th><th style={thR}>Attendance rate</th><th style={thR}>Unauthorized rate</th></tr></thead>
                <tbody>
                  {teamStats.map((t, i) => {
                    const isSelected = t.team === team;
                    return (
                      <tr key={t.team} onClick={() => handleTeamClick(t.team)} style={{ borderTop: `1px solid ${colors.line}`, cursor: 'pointer', borderLeft: isSelected ? `3px solid ${colors.select}` : '3px solid transparent', background: isSelected ? `${colors.select}22` : (i % 2 ? 'rgba(0,0,0,0.015)' : 'transparent') }}>
                        <td style={{ ...td, fontWeight: isSelected ? 700 : 500, color: isSelected ? colors.select : colors.ink }}>{t.team}</td>
                        <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{t.headcount}</td>
                        <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace", color: t.rate < 60 ? colors.alert : t.rate < 80 ? colors.warn : colors.good }}>{t.rate}%</td>
                        <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace", color: t.unauthRate > 15 ? colors.alert : colors.ink }}>{t.unauthRate}%</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div style={{ fontSize: 12, color: colors.muted, marginTop: 10 }}>Click a row to filter every tab to that team.</div>
          </section>
        )}

        {tab === 'Employees' && (
          <section>
            <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 14, flexWrap: 'wrap', gap: 8 }}>
              <h2 style={{ fontSize: 16, fontWeight: 600, margin: 0 }}>By employee <span style={{ color: colors.muted, fontWeight: 400 }}>&middot; {scopeLabel}{team !== 'All teams' && ` · ${team}`}</span></h2>
              <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search name or ID" style={{ ...selectStyle, width: 200 }} />
            </div>

            {displayedMatch && (
              <div style={{ border: `1px solid ${colors.select}`, borderRadius: 4, overflow: 'hidden', background: colors.panel, marginBottom: 16 }}>
                <div style={{ padding: '14px 16px', borderBottom: `1px solid ${colors.line}`, background: `${colors.select}14` }}>
                  <div style={{ fontWeight: 600, fontSize: 14 }}>{displayedMatch.name}<span style={{ color: colors.muted, fontFamily: "'IBM Plex Mono', monospace", fontSize: 11.5, marginLeft: 8, fontWeight: 400 }}>{displayedMatch.id}</span></div>
                  <div style={{ fontSize: 12.5, color: colors.muted, marginTop: 2 }}>{displayedMatch.team}</div>
                </div>
                <div style={{ maxHeight: 340, overflowY: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead><tr style={{ position: 'sticky', top: 0, background: colors.panel }}>
                      <th style={th}>Day</th><th style={th}>Date</th><th style={th}>Status</th>
                      <th style={thR}>In</th><th style={thR}>Out</th><th style={thR}>Hours</th>
                    </tr></thead>
                    <tbody>
                      {scopeDates.map((date, i) => {
                        const rec = weekdayRecordsAll.find((r) => r.employeeId === displayedMatch.id && r.date === date);
                        const status = rec ? dayStatus(rec) : 'unauthorized';
                        const c = STATUS_COLOR[status];
                        const label = rec ? (rec.isHoliday ? rec.holidayName : (leaveLabel(rec) || STATUS_LABEL[status])) : 'No record';
                        return (
                          <tr key={date} style={{ borderTop: `1px solid ${colors.line}`, background: i % 2 ? 'rgba(0,0,0,0.015)' : 'transparent' }}>
                            <td style={{ ...td, fontWeight: 500 }}>{dayLabel(date)}</td>
                            <td style={{ ...td, color: colors.muted }}>{shortDate(date)}</td>
                            <td style={{ ...td, color: c, fontWeight: 500 }}>
                              {label}
                              {rec?.present && <SourceDot source={rec.source} />}
                              {rec?.shiftAnomaly && <span title="Off-shift attendance — flagged for review" style={{ marginLeft: 6, color: colors.anomaly, fontSize: 11 }}>&#9888;</span>}
                            </td>
                            <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{rec?.checkIn || '\u2014'}</td>
                            <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{rec?.checkOut || '\u2014'}</td>
                            <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{rec?.hours ? rec.hours.toFixed(1) : '\u2014'}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            <div style={{ border: `1px solid ${colors.line}`, borderRadius: 4, overflow: 'hidden', background: colors.panel }}>
              <div style={{ maxHeight: 480, overflowY: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead><tr style={{ position: 'sticky', top: 0, background: colors.panel, boxShadow: `0 1px 0 ${colors.line}` }}>
                    {[['name', 'Name'], ['team', 'Team'], ['present', 'Present'], ['onLeave', 'On leave'], ['unauthorized', 'No record'], ['avgHours', 'Avg hrs/day'], ['overtime', 'OT hrs'], ['anomalyDays', 'Off-shift']].map(([key, label]) => (
                      <th key={key} onClick={() => toggleSort(key)} style={{ ...(key === 'name' || key === 'team' ? th : thR), cursor: 'pointer', userSelect: 'none' }}>{label}{sortKey === key ? (sortDir === 'asc' ? ' \u2191' : ' \u2193') : ''}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {filtered.map((e, i) => {
                      const isSelected = e.id === selectedEmpId;
                      return (
                        <tr key={e.id} onClick={() => setSelectedEmpId(isSelected ? null : e.id)} style={{ borderTop: `1px solid ${colors.line}`, cursor: 'pointer', borderLeft: isSelected ? `3px solid ${colors.select}` : (e.unauthorized >= 3 ? `3px solid ${colors.alert}` : (e.anomalyDays > 0 ? `3px solid ${colors.anomaly}` : '3px solid transparent')), background: isSelected ? `${colors.select}22` : (i % 2 ? 'rgba(0,0,0,0.015)' : 'transparent') }}>
                          <td style={{ ...td, fontWeight: isSelected ? 700 : 500, color: isSelected ? colors.select : colors.ink }}>{e.name}<span style={{ color: colors.muted, fontFamily: "'IBM Plex Mono', monospace", fontSize: 11.5, marginLeft: 8, fontWeight: 400 }}>{e.id}</span></td>
                          <td style={{ ...td, fontSize: 12.5 }}>{e.team}</td>
                          <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{e.present} / {scopeDates.length}</td>
                          <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace", color: colors.warn }}>{e.onLeave || '\u2014'}</td>
                          <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace", color: e.unauthorized >= 3 ? colors.alert : colors.ink }}>{e.unauthorized || '\u2014'}</td>
                          <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{e.avgHours || '\u2014'}</td>
                          <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{e.overtime ? e.overtime.toFixed(1) : '\u2014'}</td>
                          <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace", color: e.anomalyDays > 0 ? colors.anomaly : colors.ink }}>{e.anomalyDays || '\u2014'}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
            <div style={{ fontSize: 12, color: colors.muted, marginTop: 10 }}>{filtered.length} of {totalEmployees} employees shown. Click a row to pin the detail view above.</div>
          </section>
        )}

        {tab === 'Anomalies & Leave' && (
          <>
            <section style={{ marginBottom: 36 }}>
              <h2 style={{ fontSize: 16, fontWeight: 600, margin: '0 0 4px' }}>Chronic unauthorized absence <span style={{ color: colors.muted, fontWeight: 400 }}>&middot; {scopeLabel}{team !== 'All teams' && ` · ${team}`}</span></h2>
              <div style={{ fontSize: 13, color: colors.muted, marginBottom: 14 }}>{chronicList.length} employee{chronicList.length === 1 ? '' : 's'} with 3+ days absent and no leave on record in this view.</div>
              <div style={{ border: `1px solid ${colors.line}`, borderRadius: 4, overflow: 'hidden', background: colors.panel }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead><tr><th style={th}>Name</th><th style={th}>Team</th><th style={th}>{scopeLabel}</th><th style={thR}>Unauthorized</th></tr></thead>
                  <tbody>
                    {chronicList.map((e, i) => (
                      <tr key={e.id} style={{ borderTop: `1px solid ${colors.line}`, background: i % 2 ? 'rgba(0,0,0,0.015)' : 'transparent' }}>
                        <td style={{ ...td, fontWeight: 500 }}>{e.name}<span style={{ color: colors.muted, fontFamily: "'IBM Plex Mono', monospace", fontSize: 11.5, marginLeft: 8 }}>{e.id}</span></td>
                        <td style={{ ...td, fontSize: 12.5 }}>{e.team}</td>
                        <td style={td}><DayChips empId={e.id} dates={scopeDates} weekdayRecordsAll={weekdayRecordsAll} /></td>
                        <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace", color: colors.alert }}>{e.unauthorized}</td>
                      </tr>
                    ))}
                    {chronicList.length === 0 && (<tr><td colSpan={4} style={{ padding: '24px 16px', textAlign: 'center', color: colors.muted }}>No one crossed the threshold in this view.</td></tr>)}
                  </tbody>
                </table>
              </div>
            </section>

            <section style={{ marginBottom: 36 }}>
              <h2 style={{ fontSize: 16, fontWeight: 600, margin: '0 0 4px' }}>Off-shift attendance <span style={{ color: colors.muted, fontWeight: 400 }}>&middot; {scopeLabel}</span></h2>
              <div style={{ fontSize: 13, color: colors.muted, marginBottom: 14 }}>
                Presence recorded outside the employee's assigned shift window \u2014 e.g. a night-shift employee attending a daytime meeting. This is a flag for review, never a rejection: the person was genuinely present.
              </div>
              <div style={{ border: `1px solid ${colors.line}`, borderRadius: 4, overflow: 'hidden', background: colors.panel }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead><tr><th style={th}>Name</th><th style={th}>Date</th><th style={th}>Assigned shift</th><th style={th}>Actual window matched</th><th style={thR}>In \u2013 Out</th></tr></thead>
                  <tbody>
                    {anomalyRecords.map((r, i) => (
                      <tr key={`${r.employeeId}-${r.date}`} style={{ borderTop: `1px solid ${colors.line}`, background: i % 2 ? 'rgba(0,0,0,0.015)' : 'transparent' }}>
                        <td style={{ ...td, fontWeight: 500 }}>{r.name}</td>
                        <td style={{ ...td, color: colors.muted }}>{shortDate(r.date)}</td>
                        <td style={td}>{r.assignedShift || '\u2014'}</td>
                        <td style={{ ...td, color: colors.anomaly, fontWeight: 500 }}>{r.matchedShift || '\u2014'}</td>
                        <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{r.checkIn || '\u2014'} \u2013 {r.checkOut || '\u2014'}</td>
                      </tr>
                    ))}
                    {anomalyRecords.length === 0 && (<tr><td colSpan={5} style={{ padding: '24px 16px', textAlign: 'center', color: colors.muted }}>No off-shift attendance flagged in this view \u2014 also expected until shift assignment data actually arrives from Zoho.</td></tr>)}
                  </tbody>
                </table>
              </div>
            </section>

            <section>
              <h2 style={{ fontSize: 16, fontWeight: 600, margin: '0 0 4px' }}>Leave <span style={{ color: colors.muted, fontWeight: 400 }}>&middot; {scopeLabel}</span></h2>
              <div style={{ border: `1px solid ${colors.line}`, borderRadius: 4, overflow: 'hidden', background: colors.panel, marginTop: 14 }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead><tr><th style={th}>Name</th><th style={th}>Date</th><th style={th}>Type</th><th style={th}>Status</th></tr></thead>
                  <tbody>
                    {leaveRecords.map((r, i) => (
                      <tr key={`${r.employeeId}-${r.date}`} style={{ borderTop: `1px solid ${colors.line}`, background: i % 2 ? 'rgba(0,0,0,0.015)' : 'transparent' }}>
                        <td style={{ ...td, fontWeight: 500 }}>{r.name}</td>
                        <td style={{ ...td, color: colors.muted }}>{shortDate(r.date)}</td>
                        <td style={{ ...td, color: colors.warn }}>{leaveLabel(r)}</td>
                        <td style={td}>{r.leaves.map((l) => l.status).join(', ')}</td>
                      </tr>
                    ))}
                    {leaveRecords.length === 0 && (<tr><td colSpan={4} style={{ padding: '24px 16px', textAlign: 'center', color: colors.muted }}>No leave recorded in this view.</td></tr>)}
                  </tbody>
                </table>
              </div>
            </section>
          </>
        )}
      </div>
    </div>
  );
}
