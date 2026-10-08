import React, { useState, useMemo } from 'react';
import { BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { colors } from './theme.js';
import logoUrl from './assets/tbl-logo.svg';
import AuthHeader from './components/AuthHeader.jsx';

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
// Bi-weekly = semi-monthly halves: 1st–15th and 16th–month-end.
function halfOf(dateStr) {
  return parseDate(dateStr).getDate() <= 15 ? 'H1' : 'H2';
}
const HALF_LABEL = { H1: '1–15', H2: '16–end' };

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



const STATUS_COLOR = {
  present: colors.good, holiday: colors.holiday, onLeave: colors.warn,
  unauthorized: colors.alert,
};
const STATUS_LABEL = {
  present: 'Present', holiday: 'Public holiday', onLeave: 'On leave',
  unauthorized: 'Absent',
};

// Trust tier: how strong is the evidence behind "present"? Biometric is a
// physical scan; zoho_manual is self-attested; migrated is historical
// import predating this distinction entirely.
const SOURCE_COLOR = { biometric: colors.good, zoho_manual: colors.warn, migrated: colors.neutral, wfh: colors.select };
const SOURCE_LABEL = { biometric: 'Biometric (verified)', zoho_manual: 'Self-reported check-in', migrated: 'Migrated historical data', wfh: 'WFH approved' };

function leaveLabel(rec) {
  if (!rec.leaves.length) return '';
  return rec.leaves.map((l) => l.type).join(', ');
}

function computeDerived(records) {
  // allDates: EVERY date present in the data, weekends included — the period
  // navigator must reflect data reality so gaps can be spotted. Working-day
  // stats below still exclude weekends from rate denominators.
  const allDates = [...new Set(records.map((r) => r.date))].sort();
  const weekdayRecordsAll = records.filter((r) => !isWeekend(r.date));
  const MONTHS = [...new Set(allDates.map(monthKey))].sort().map((key) => ({
    key, label: monthName(allDates.find((d) => monthKey(d) === key)),
  }));
  const ALL_TEAMS = [...new Set(weekdayRecordsAll.map((r) => r.team))].sort();
  return { allDates, weekdayRecordsAll, MONTHS, ALL_TEAMS };
}

function DayChips({ empId, dates, weekdayRecordsAll }) {
  const byDate = {};
  weekdayRecordsAll.forEach((r) => { if (r.employeeId === empId) byDate[r.date] = r; });
  return (
    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', maxWidth: 280 }}>
      {dates.map((date) => {
        const rec = byDate[date];
        if (!rec && isWeekend(date)) {
          return (
            <div
              key={date}
              title={`${dayLabel(date)} ${shortDate(date)} — weekend (no shift expected)`}
              style={{
                width: 22, height: 22, borderRadius: 4, display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 10.5, fontFamily: "'IBM Plex Mono', monospace", fontWeight: 600,
                background: colors.paper, color: colors.muted, border: `1px dashed ${colors.line}`,
                flexShrink: 0,
              }}
            >
              {dayLabel(date)[0]}
            </div>
          );
        }
        const status = rec ? dayStatus(rec) : 'unauthorized';
        const c = STATUS_COLOR[status];
        const label = rec ? (rec.isHoliday ? rec.holidayName : (leaveLabel(rec) || STATUS_LABEL[status])) : 'No record';
        return (
          <div
            key={date}
            title={`${dayLabel(date)} ${shortDate(date)} — ${label}${rec?.shiftAnomaly ? ' (off-shift)' : ''}`}
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

const TABS = ['Overview', 'Teams', 'Employees', 'Anomalies & Leave', 'Sync check'];

// Overview opens on the current month + current bi-weekly half so the first
// thing seen is "now", not a 10-month aggregate. Falls back to the latest
// month with data when the current month isn't in the dataset yet.
function defaultMonthKey(MONTHS) {
  if (!MONTHS.length) return 'all';
  const now = new Date();
  const key = `${now.getFullYear()}-${now.getMonth()}`;
  if (MONTHS.some((m) => m.key === key)) return key;
  return MONTHS[MONTHS.length - 1].key;
}
function defaultHalf(monthKey) {
  const now = new Date();
  if (monthKey !== 'all' && monthKey === `${now.getFullYear()}-${now.getMonth()}`) {
    return now.getDate() <= 15 ? 'H1' : 'H2';
  }
  return 'all';
}

export default function AttendanceDashboard({ records, coverage }) {
  const { allDates, weekdayRecordsAll, MONTHS, ALL_TEAMS } = useMemo(() => computeDerived(records), [records]);

  const [tab, setTab] = useState('Overview');
  const [selectedTeams, setSelectedTeams] = useState([]); // empty = all teams
  const [shiftFilter, setShiftFilter] = useState('all'); // all|day|night|hybrid
  // Period navigation: month -> bi-weekly half (1-15 / 16-end) -> single day.
  const [monthFilter, setMonthFilter] = useState(() => defaultMonthKey(MONTHS));
  const [halfFilter, setHalfFilter] = useState(() => defaultHalf(defaultMonthKey(MONTHS)));
  const [dayFilter, setDayFilter] = useState('all'); // all|<date>
  const [query, setQuery] = useState('');
  const [sortKey, setSortKey] = useState('unauthorized');
  const [sortDir, setSortDir] = useState('desc');
  const [selectedEmpId, setSelectedEmpId] = useState(null);

  const SHIFTS = ['all', 'day', 'night', 'hybrid'];

  const teamFiltered = useMemo(() => {
    let rows = weekdayRecordsAll;
    if (selectedTeams.length > 0) rows = rows.filter((r) => selectedTeams.includes(r.team));
    if (shiftFilter !== 'all') rows = rows.filter((r) => (r.assignedShift || r.matchedShift || '').toLowerCase() === shiftFilter);
    return rows;
  }, [selectedTeams, shiftFilter, weekdayRecordsAll]);

  // Dates surviving the month/half picker (weekends included — nav shows data).
  const visibleDates = useMemo(() => allDates.filter((d) => {
    if (monthFilter !== 'all' && monthKey(d) !== monthFilter) return false;
    if (halfFilter !== 'all' && halfOf(d) !== halfFilter) return false;
    return true;
  }), [allDates, monthFilter, halfFilter]);

  function handleMonthChange(val) { setMonthFilter(val); setHalfFilter('all'); setDayFilter('all'); }
  function handleHalfChange(val) { setHalfFilter(val); setDayFilter('all'); }
  function toggleTeam(t) {
    setSelectedTeams((prev) => prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]);
  }
  function handleTeamClick(t) { toggleTeam(t); }
  function clearTeams() { setSelectedTeams([]); }

  const monthLabel = monthFilter === 'all'
    ? 'All months'
    : (MONTHS.find((m) => m.key === monthFilter)?.label || monthFilter);
  const isSingleDay = dayFilter !== 'all';
  const scopeDates = useMemo(() => {
    if (isSingleDay) return [dayFilter];
    return visibleDates;
  }, [isSingleDay, dayFilter, visibleDates]);
  const scopeLabel = isSingleDay
    ? `${dayLabel(dayFilter)} ${shortDate(dayFilter)}`
    : halfFilter === 'all'
      ? (monthFilter === 'all' ? `All ${allDates.length} days` : `All of ${monthLabel}`)
      : `${monthLabel} · ${HALF_LABEL[halfFilter]}`;

  const scopeRecords = useMemo(() => {
    const dateSet = new Set(scopeDates);
    return teamFiltered.filter((r) => dateSet.has(r.date));
  }, [teamFiltered, scopeDates]);

  // Day-by-day attendance trend across the current scope.
  const trendData = useMemo(() => scopeDates.map((d) => {
    const recs = teamFiltered.filter((r) => r.date === d && dayStatus(r) !== 'holiday');
    const present = recs.filter((r) => r.present).length;
    const unauthorized = recs.filter((r) => dayStatus(r) === 'unauthorized').length;
    const rate = recs.length ? Math.round((present / recs.length) * 1000) / 10 : 0;
    const unauthRate = recs.length ? Math.round((unauthorized / recs.length) * 1000) / 10 : 0;
    return { label: shortDate(d), rate, unauthRate };
  }), [teamFiltered, scopeDates]);

  const chartData = useMemo(() => scopeDates.map((d) => {
    const recs = scopeRecords.filter((r) => r.date === d);
    const present = recs.filter((r) => dayStatus(r) === 'present').length;
    const holiday = recs.filter((r) => dayStatus(r) === 'holiday').length;
    const onLeave = recs.filter((r) => dayStatus(r) === 'onLeave').length;
    const unauthorized = recs.filter((r) => dayStatus(r) === 'unauthorized').length;
    return { label: isSingleDay ? shortDate(d) : dayLabel(d), present, holiday, onLeave, unauthorized, total: recs.length };
  }), [scopeRecords, scopeDates, isSingleDay]);

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
  const wfhRecords = useMemo(
    () => scopeRecords.filter((r) => r.wfh).sort((a, b) => b.date.localeCompare(a.date)),
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

  // --- Sync-check derived data (DB truth vs what this page loaded) --------
  // Daily headcount is NOT uniform across months (roster grew ~113 in Jan to
  // ~132 in Aug), so "expected" is the median day, not the max. Only days
  // under half the median, zero-row dates, or missing weekdays fail the check.
  const syncInfo = useMemo(() => {
    const dbRows = coverage?.attendance_rows ?? null;
    const loadedRows = records.length;
    const perDate = coverage?.per_date ?? [];
    const counts = perDate.map((d) => d.count).sort((a, b) => a - b);
    const typical = counts.length ? counts[Math.floor(counts.length / 2)] : 0;
    const shortDates = perDate.filter((d) => d.count < typical * 0.5);
    const zeroDates = perDate.filter((d) => d.count === 0);
    // Weekdays inside the DB date range with zero rows = genuinely missing.
    const have = new Set(perDate.map((d) => d.date));
    const missingWeekdays = [];
    if (coverage?.date_min && coverage?.date_max) {
      const cur = parseDate(coverage.date_min);
      const end = parseDate(coverage.date_max);
      while (cur <= end) {
        const iso = cur.toISOString().slice(0, 10);
        const dow = cur.getDay();
        if (dow !== 0 && dow !== 6 && !have.has(iso)) missingWeekdays.push(iso);
        cur.setDate(cur.getDate() + 1);
      }
    }
    const complete = dbRows !== null
      && loadedRows === dbRows
      && shortDates.length === 0
      && zeroDates.length === 0
      && missingWeekdays.length === 0;
    return { dbRows, loadedRows, perDate, typical, shortDates, zeroDates, missingWeekdays, complete };
  }, [coverage, records]);

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

        <header style={{ marginBottom: 24, borderBottom: `2px solid ${colors.primary}`, paddingBottom: 18, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 24, flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 24 }}>
            <img src={logoUrl} alt="Technobrain" style={{ height: 46, width: 'auto', display: 'block', flexShrink: 0 }} />
            <div style={{ width: 1, height: 32, background: colors.line, flexShrink: 0 }} />
            <h1 style={{ fontFamily: "'Fraunces', Georgia, serif", fontWeight: 700, fontSize: 24, margin: 0, lineHeight: 1.2, color: colors.slate, whiteSpace: 'nowrap' }}>
              Attendance Dashboard
            </h1>
          </div>
          <AuthHeader />
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

        {tab !== 'Sync check' && (
        <section style={{ marginBottom: 20 }}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', background: colors.panel, border: `1px solid ${colors.line}`, borderRadius: 4, padding: '8px 10px', marginBottom: 10 }}>
            <span style={{ fontSize: 12, color: colors.muted, fontWeight: 600, marginRight: 4 }}>Month:</span>
            <select value={monthFilter} onChange={(e) => handleMonthChange(e.target.value)} style={selectStyle}>
              <option value="all">All months ({allDates.length} days)</option>
              {MONTHS.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
            </select>
            <span style={{ fontSize: 12, color: colors.muted, fontWeight: 600, marginLeft: 8 }}>Bi-weekly:</span>
            {['all', 'H1', 'H2'].map((h) => (
              <button
                key={h}
                onClick={() => handleHalfChange(h)}
                style={{
                  fontFamily: 'inherit', fontSize: 12.5, padding: '7px 14px', cursor: 'pointer',
                  border: `1px solid ${halfFilter === h ? colors.ink : colors.line}`,
                  background: halfFilter === h ? colors.ink : colors.panel,
                  color: halfFilter === h ? colors.paper : colors.ink, borderRadius: 20,
                }}
              >
                {h === 'all' ? 'Whole month' : `${h} (${HALF_LABEL[h]})`}
              </button>
            ))}
            <span style={{ fontSize: 12, color: colors.muted, fontWeight: 600, marginLeft: 8 }}>Day:</span>
            <select value={dayFilter} onChange={(e) => setDayFilter(e.target.value)} style={{ ...selectStyle, maxWidth: 220 }}>
              <option value="all">All {visibleDates.length} days in view</option>
              {visibleDates.map((d) => (
                <option key={d} value={d}>{dayLabel(d)} {shortDate(d)}{isWeekend(d) ? ' (weekend)' : ''}</option>
              ))}
            </select>
            <select value={shiftFilter} onChange={(e) => setShiftFilter(e.target.value)} style={{ ...selectStyle, marginLeft: 'auto' }} title="Filter by shift (view only until Zoho provides assignment)">
              <option value="all">All shifts</option><option value="day">Day</option><option value="night">Night</option><option value="hybrid">Hybrid</option>
            </select>
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', background: colors.panel, border: `1px solid ${colors.line}`, borderRadius: 4, padding: '8px 10px' }}>
            <span style={{ fontSize: 12, color: colors.muted, fontWeight: 600, marginRight: 4 }}>Teams:</span>
            {ALL_TEAMS.map((t) => {
              const active = selectedTeams.includes(t);
              return (
                <button key={t} onClick={() => toggleTeam(t)} style={{ fontFamily: 'inherit', fontSize: 12, padding: '5px 10px', cursor: 'pointer', border: `1px solid ${active ? colors.select : colors.line}`, background: active ? colors.select : colors.panel, color: active ? '#fff' : colors.ink, borderRadius: 20, fontWeight: active ? 600 : 400 }}>
                  {t}{active ? ' ×' : ''}
                </button>
              );
            })}
            {selectedTeams.length > 0 && <button onClick={clearTeams} style={{ fontFamily: 'inherit', fontSize: 12, padding: '5px 10px', cursor: 'pointer', border: `1px solid ${colors.line}`, background: colors.paper, color: colors.muted, borderRadius: 20 }}>Clear ({selectedTeams.length})</button>}
            {selectedTeams.length === 0 && <span style={{ fontSize: 12, color: colors.muted }}>All teams included. Click to exclude/include. Recomputes all tabs.</span>}
            {selectedTeams.length > 0 && <span style={{ fontSize: 12, color: colors.select }}>{selectedTeams.length} of {ALL_TEAMS.length} selected</span>}
          </div>
        </section>
        )}

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
            <div style={{ fontSize: 12, color: colors.muted, marginBottom: 32 }}>Figures above reflect: <strong style={{ color: colors.ink }}>{scopeLabel}</strong>{selectedTeams.length > 0 && ` · ${selectedTeams.join(', ')}`}{shiftFilter !== 'all' && ` · ${shiftFilter} shift`}. Public holidays are excluded from the rate calculations. Weekend dates carry no expected shift and are excluded from rates.</div>

            <section style={{ marginBottom: 36 }}>
              <h2 style={{ fontSize: 16, fontWeight: 600, margin: '0 0 14px' }}>Attendance rate, day by day {selectedTeams.length > 0 && <span style={{ color: colors.muted, fontWeight: 400 }}>&middot; {selectedTeams.join(', ')}</span>}{shiftFilter !== 'all' && <span style={{ color: colors.muted, fontWeight: 400 }}> &middot; {shiftFilter}</span>}</h2>
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
              <h2 style={{ fontSize: 16, fontWeight: 600, margin: '0 0 14px' }}>{isSingleDay ? 'Single-day breakdown' : 'Daily breakdown'} <span style={{ color: colors.muted, fontWeight: 400 }}>&middot; {scopeLabel}</span></h2>
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
                    const isSelected = selectedTeams.includes(t.team);
                    return (
                      <tr key={t.team} onClick={() => handleTeamClick(t.team)} style={{ borderTop: `1px solid ${colors.line}`, cursor: 'pointer', borderLeft: isSelected ? `3px solid ${colors.select}` : '3px solid transparent', background: isSelected ? `${colors.select}14` : (i % 2 ? 'rgba(0,0,0,0.015)' : 'transparent') }}>
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
            <div style={{ fontSize: 12, color: colors.muted, marginTop: 10 }}>Click a row to include/exclude that team. Use the chip row above to multi-select. Recomputes all tabs.</div>
          </section>
        )}

        {tab === 'Employees' && (
          <section>
            <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 14, flexWrap: 'wrap', gap: 8 }}>
              <h2 style={{ fontSize: 16, fontWeight: 600, margin: 0 }}>By employee <span style={{ color: colors.muted, fontWeight: 400 }}>&middot; {scopeLabel}{selectedTeams.length > 0 && ` · ${selectedTeams.join(', ')}`}{shiftFilter !== 'all' && ` · ${shiftFilter}`}</span></h2>
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
                        const weekend = isWeekend(date);
                        const status = rec ? dayStatus(rec) : 'unauthorized';
                        const c = weekend && !rec ? colors.muted : STATUS_COLOR[status];
                        const label = rec ? (rec.isHoliday ? rec.holidayName : (leaveLabel(rec) || STATUS_LABEL[status])) : (weekend ? 'Weekend' : 'No record');
                        return (
                          <tr key={date} style={{ borderTop: `1px solid ${colors.line}`, background: i % 2 ? 'rgba(0,0,0,0.015)' : 'transparent' }}>
                            <td style={{ ...td, fontWeight: 500 }}>{dayLabel(date)}</td>
                            <td style={{ ...td, color: colors.muted }}>{shortDate(date)}</td>
                            <td style={{ ...td, color: c, fontWeight: 500 }}>
                              {label}
                              {rec?.wfh && <span style={{ marginLeft: 6, fontSize: 10, color: colors.select, border: `1px solid ${colors.select}`, borderRadius: 3, padding: '1px 4px' }}>WFH</span>}
                              {rec?.present && !rec?.wfh && <SourceDot source={rec.source} />}
                              {rec?.shiftAnomaly && <span title="Off-shift attendance flagged for review" style={{ marginLeft: 6, color: colors.anomaly, fontSize: 11 }}>&#9888;</span>}
                            </td>
                            <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{rec?.checkIn || '—'}</td>
                            <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{rec?.checkOut || '—'}</td>
                            <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{rec?.hours ? rec.hours.toFixed(1) : '—'}</td>
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
                      <th key={key} onClick={() => toggleSort(key)} style={{ ...(key === 'name' || key === 'team' ? th : thR), cursor: 'pointer', userSelect: 'none' }}>{label}{sortKey === key ? (sortDir === 'asc' ? ' ↑' : ' ↓') : ''}</th>
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
                          <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace", color: colors.warn }}>{e.onLeave || '—'}</td>
                          <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace", color: e.unauthorized >= 3 ? colors.alert : colors.ink }}>{e.unauthorized || '—'}</td>
                          <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{e.avgHours || '—'}</td>
                          <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{e.overtime ? e.overtime.toFixed(1) : '—'}</td>
                          <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace", color: e.anomalyDays > 0 ? colors.anomaly : colors.ink }}>{e.anomalyDays || '—'}</td>
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
              <h2 style={{ fontSize: 16, fontWeight: 600, margin: '0 0 4px' }}>Chronic unauthorized absence <span style={{ color: colors.muted, fontWeight: 400 }}>&middot; {scopeLabel}{selectedTeams.length > 0 && ` · ${selectedTeams.join(', ')}`}{shiftFilter !== 'all' && ` · ${shiftFilter}`}</span></h2>
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
                Presence recorded outside the employee assigned shift window. Flag for review only.
              </div>
              <div style={{ border: `1px solid ${colors.line}`, borderRadius: 4, overflow: 'hidden', background: colors.panel }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead><tr><th style={th}>Name</th><th style={th}>Date</th><th style={th}>Assigned shift</th><th style={th}>Actual window matched</th></tr></thead>
                  <tbody>
                    {anomalyRecords.map((r, i) => (
                      <tr key={`${r.employeeId}-${r.date}`} style={{ borderTop: `1px solid ${colors.line}`, background: i % 2 ? 'rgba(0,0,0,0.015)' : 'transparent' }}>
                        <td style={{ ...td, fontWeight: 500 }}>{r.name}</td>
                        <td style={{ ...td, color: colors.muted }}>{shortDate(r.date)}</td>
                        <td style={td}>{r.assignedShift || '-'}</td>
                        <td style={{ ...td, color: colors.anomaly, fontWeight: 500 }}>{r.matchedShift || '-'}</td>
                      </tr>
                    ))}
                    {anomalyRecords.length === 0 && (<tr><td colSpan={4} style={{ padding: '24px 16px', textAlign: 'center', color: colors.muted }}>No off-shift attendance flagged in this view. Expected until shift data arrives from Zoho.</td></tr>)}
                  </tbody>
                </table>
              </div>
            </section>

            <section style={{ marginBottom: 36 }}>
              <h2 style={{ fontSize: 16, fontWeight: 600, margin: '0 0 4px' }}>Work from home <span style={{ color: colors.muted, fontWeight: 400 }}>&middot; {scopeLabel}</span></h2>
              <div style={{ fontSize: 13, color: colors.muted, marginBottom: 14 }}>Approved WFH overrides. Counts as present. Managed by team lead or admin via API.</div>
              <div style={{ border: `1px solid ${colors.line}`, borderRadius: 4, overflow: 'hidden', background: colors.panel, marginTop: 14 }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead><tr><th style={th}>Name</th><th style={th}>Date</th><th style={th}>Team</th></tr></thead>
                  <tbody>
                    {wfhRecords.map((r, i) => (
                      <tr key={`${r.employeeId}-${r.date}`} style={{ borderTop: `1px solid ${colors.line}`, background: i % 2 ? 'rgba(0,0,0,0.015)' : 'transparent' }}>
                        <td style={{ ...td, fontWeight: 500 }}>{r.name}<span style={{ marginLeft: 6, fontSize: 11, color: colors.select, border: `1px solid ${colors.select}`, borderRadius: 3, padding: '1px 4px' }}>WFH</span></td>
                        <td style={{ ...td, color: colors.muted }}>{shortDate(r.date)}</td>
                        <td style={{ ...td, fontSize: 12.5 }}>{r.team}</td>
                      </tr>
                    ))}
                    {wfhRecords.length === 0 && (<tr><td colSpan={3} style={{ padding: '24px 16px', textAlign: 'center', color: colors.muted }}>No WFH approvals in this view.</td></tr>)}
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

        {tab === 'Sync check' && (
          <>
            <section style={{ marginBottom: 24 }}>
              <h2 style={{ fontSize: 16, fontWeight: 600, margin: '0 0 14px' }}>Did everything sync?</h2>
              {!coverage && (
                <div style={{ border: `1px solid ${colors.warn}`, borderRadius: 4, background: '#FDF6E3', padding: '14px 16px', fontSize: 13 }}>
                  Coverage endpoint unavailable — showing frontend-loaded rows only. Check that the API restarted after the update.
                </div>
              )}
              {coverage && (
                <div style={{
                  border: `1px solid ${syncInfo.complete ? colors.good : colors.alert}`,
                  borderRadius: 4, overflow: 'hidden', background: colors.panel,
                }}>
                  <div style={{
                    padding: '14px 16px', fontWeight: 600, fontSize: 14,
                    background: syncInfo.complete ? 'rgba(58,107,82,0.1)' : 'rgba(166,61,47,0.08)',
                    color: syncInfo.complete ? colors.good : colors.alert,
                    borderBottom: `1px solid ${colors.line}`,
                  }}>
                    {syncInfo.complete
                      ? `Complete — all ${syncInfo.dbRows} DB rows loaded, no thin or missing dates, no missing weekdays.`
                      : 'Incomplete — see the gaps below.'}
                  </div>
                  <div style={{ display: 'flex', flexWrap: 'wrap' }}>
                    {[
                      { label: 'Rows in DB (attendance_records)', value: syncInfo.dbRows },
                      { label: 'Rows loaded by this page', value: syncInfo.loadedRows },
                      { label: 'DB date range', value: coverage.date_min && coverage.date_max ? `${coverage.date_min} → ${coverage.date_max}` : '—' },
                      { label: 'Employees / Teams', value: `${coverage.employees} / ${coverage.teams}` },
                      { label: 'Leave rows / Holidays / WFH', value: `${coverage.leave_rows} / ${coverage.holidays} / ${coverage.wfh_rows}` },
                      { label: `Typical rows per day (median)`, value: syncInfo.typical || '—' },
                    ].map((s, i) => (
                      <div key={i} style={{ flex: '1 1 200px', padding: '14px 16px', borderRight: `1px solid ${colors.line}` }}>
                        <div style={{ fontSize: 12, color: colors.muted, marginBottom: 6 }}>{s.label}</div>
                        <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 18, fontWeight: 500 }}>{s.value}</div>
                      </div>
                    ))}
                  </div>
                  {(syncInfo.shortDates.length > 0 || syncInfo.zeroDates.length > 0 || syncInfo.missingWeekdays.length > 0 || syncInfo.loadedRows !== syncInfo.dbRows) && (
                    <div style={{ padding: '12px 16px', fontSize: 13, borderTop: `1px solid ${colors.line}`, color: colors.alert }}>
                      {syncInfo.loadedRows !== syncInfo.dbRows && (
                        <div>Page loaded {syncInfo.loadedRows} of {syncInfo.dbRows} DB rows — pagination is falling behind.</div>
                      )}
                      {syncInfo.shortDates.map((d) => (
                        <div key={d.date}>{d.date} has only {d.count} rows (typical day: {syncInfo.typical}).</div>
                      ))}
                      {syncInfo.zeroDates.map((d) => (
                        <div key={d.date}>{d.date} has zero rows in the DB.</div>
                      ))}
                      {syncInfo.missingWeekdays.map((d) => (
                        <div key={d}>{d} is a weekday with zero rows in the DB — that day never synced.</div>
                      ))}
                    </div>
                  )}
                  {syncInfo.complete && (
                    <div style={{ padding: '12px 16px', fontSize: 12.5, borderTop: `1px solid ${colors.line}`, color: colors.muted }}>
                      Daily headcount varies because the roster grew over the months (about 113 staff/day in January, 132 by August) — that is real history, not missing data.
                    </div>
                  )}
                </div>
              )}
            </section>

            <section style={{ marginBottom: 24 }}>
              <h2 style={{ fontSize: 16, fontWeight: 600, margin: '0 0 4px' }}>Per-date coverage</h2>
              <div style={{ fontSize: 13, color: colors.muted, marginBottom: 14 }}>
                One chip per date in the DB. Green = typical day or fuller. Amber = below half the typical day. Red = zero rows. Dashed = weekend (no shift expected, shown for completeness).
              </div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', background: colors.panel, border: `1px solid ${colors.line}`, borderRadius: 4, padding: 14 }}>
                {(coverage?.per_date ?? allDates.map((d) => ({ date: d, count: records.filter((r) => r.date === d).length }))).map((d) => {
                  const weekend = isWeekend(d.date);
                  const thin = syncInfo.typical > 0 && d.count < syncInfo.typical * 0.5;
                  const empty = d.count === 0;
                  const c = empty ? colors.alert : thin ? colors.warn : colors.good;
                  return (
                    <div
                      key={d.date}
                      title={`${d.date} — ${d.count} rows${syncInfo.typical ? ` (typical day: ${syncInfo.typical})` : ''}`}
                      style={{
                        padding: '6px 10px', borderRadius: 20, fontSize: 12,
                        fontFamily: "'IBM Plex Mono', monospace",
                        background: weekend && !thin && !empty ? colors.paper : `${c}1F`,
                        color: weekend && !thin && !empty ? colors.muted : c,
                        border: weekend && !thin && !empty ? `1px dashed ${colors.line}` : `1px solid ${c}4D`,
                        fontWeight: 600, cursor: 'pointer',
                      }}
                      onClick={() => {
                        const mk = monthKey(d.date);
                        setMonthFilter(mk); setHalfFilter(halfOf(d.date)); setDayFilter(d.date); setTab('Overview');
                      }}
                    >
                      {shortDate(d.date)} · {d.count}
                    </div>
                  );
                })}
              </div>
              <div style={{ fontSize: 12, color: colors.muted, marginTop: 10 }}>Click a chip to jump to that day in the Overview tab.</div>
            </section>

            <section style={{ marginBottom: 24 }}>
              <h2 style={{ fontSize: 16, fontWeight: 600, margin: '0 0 14px' }}>Per-month totals (DB)</h2>
              <div style={{ border: `1px solid ${colors.line}`, borderRadius: 4, overflow: 'hidden', background: colors.panel }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead><tr><th style={th}>Month</th><th style={thR}>Rows</th><th style={thR}>Dates</th></tr></thead>
                  <tbody>
                    {(coverage?.per_month ?? []).map((m, i) => {
                      const dates = (coverage?.per_date ?? []).filter((d) => d.date.slice(0, 7) === m.month).length;
                      return (
                        <tr key={m.month} style={{ borderTop: `1px solid ${colors.line}`, background: i % 2 ? 'rgba(0,0,0,0.015)' : 'transparent' }}>
                          <td style={{ ...td, fontWeight: 500 }}>{m.month}</td>
                          <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{m.count}</td>
                          <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{dates}</td>
                        </tr>
                      );
                    })}
                    {(!coverage || (coverage.per_month ?? []).length === 0) && (
                      <tr><td colSpan={3} style={{ padding: '24px 16px', textAlign: 'center', color: colors.muted }}>No coverage data — is the API reachable?</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </section>

            <section>
              <h2 style={{ fontSize: 16, fontWeight: 600, margin: '0 0 14px' }}>Sync log (latest runs)</h2>
              <div style={{ border: `1px solid ${colors.line}`, borderRadius: 4, overflow: 'hidden', background: colors.panel }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead><tr><th style={th}>Source</th><th style={th}>Ran at</th><th style={thR}>Processed</th><th style={thR}>Failed</th><th style={th}>Status</th><th style={th}>Notes</th></tr></thead>
                  <tbody>
                    {(coverage?.sync_log ?? []).map((s, i) => (
                      <tr key={s.id} style={{ borderTop: `1px solid ${colors.line}`, background: i % 2 ? 'rgba(0,0,0,0.015)' : 'transparent' }}>
                        <td style={{ ...td, fontFamily: "'IBM Plex Mono', monospace", fontSize: 12 }}>{s.source}</td>
                        <td style={{ ...td, color: colors.muted, fontSize: 12.5 }}>{s.run_at}</td>
                        <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{s.records_processed}</td>
                        <td style={{ ...td, textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace", color: s.records_failed > 0 ? colors.alert : colors.ink }}>{s.records_failed}</td>
                        <td style={{ ...td, color: s.status === 'complete' ? colors.good : colors.alert, fontWeight: 500 }}>{s.status}</td>
                        <td style={{ ...td, fontSize: 12.5, color: colors.muted }}>{s.notes || '—'}</td>
                      </tr>
                    ))}
                    {(!coverage || (coverage.sync_log ?? []).length === 0) && (
                      <tr><td colSpan={6} style={{ padding: '24px 16px', textAlign: 'center', color: colors.muted }}>No sync runs recorded.</td></tr>
                    )}
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
