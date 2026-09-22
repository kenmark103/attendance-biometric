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

function dayStatus(rec) {
  if (rec.present) return 'present';
  if (rec.exemption) return 'exempt';
  if (rec.leave) return 'approved';
  if (!rec.hasLeaveData) return 'unverified';
  return 'unauthorized';
}

const colors = {
  ink: '#1C2321', paper: '#F1F3EF', panel: '#FFFFFF', line: '#DBE0D9',
  muted: '#6E786F', good: '#3A6B52', alert: '#A63D2F', warn: '#B98B2E', neutral: '#8C8F7E',
  select: '#2F5D8A', exempt: '#6B5B95',
};

const STATUS_COLOR = {
  present: colors.good, exempt: colors.exempt, approved: colors.warn, unauthorized: colors.alert, unverified: colors.neutral,
};
const STATUS_LABEL = {
  present: 'Present', exempt: 'Approved arrangement', approved: 'On approved leave', unauthorized: 'Absent — no leave on record', unverified: 'Absent — no leave data available',
};

function computeDerived(RAW) {
  const records = RAW.map((r) => ({
    id: r[0], name: r[1], date: r[2], inTime: r[3], outTime: r[4],
    hours: r[5], overtime: r[6], late: !!r[7], early: !!r[8], present: !!r[9],
    team: r[10], leave: r[11] || '', hasLeaveData: !!r[12], exemption: r[13] || '',
    day: dayLabel(r[2]), weekend: isWeekend(r[2]),
  }));
  const weekdayRecordsAll = records.filter((r) => !r.weekend);
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
    w.label = `${shortDate(w.start)}–${parseDate(w.end).getDate()}`;
    const counts = {};
    w.dates.forEach((d) => { const k = monthKey(d); counts[k] = (counts[k] || 0) + 1; });
    w.month = Object.entries(counts).sort((a, b) => b[1] - a[1])[0][0];
  });
  const MONTHS = [...new Set(WEEKS.map((w) => w.month))].sort().map((key) => ({
    key, label: monthName(WEEKS.find((w) => w.month === key).dates[0]),
  }));
  const ALL_TEAMS = [...new Set(weekdayRecordsAll.map((r) => r.team))].sort();
  return { records, weekdayRecordsAll, WEEKS, MONTHS, ALL_TEAMS };
}

function DayChips({ empId, dates, weekdayRecordsAll }) {
  const byDate = {};
  weekdayRecordsAll.forEach((r) => { if (r.id === empId) byDate[r.date] = r; });
  return (
    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', maxWidth: 260 }}>
      {dates.map((date) => {
        const rec = byDate[date];
        const status = rec ? dayStatus(rec) : 'unverified';
        const c = STATUS_COLOR[status];
        const label = rec && status === 'exempt' ? rec.exemption : (rec && rec.leave ? rec.leave : STATUS_LABEL[status]);
        return (
          <div
            key={date}
            title={`${dayLabel(date)} ${shortDate(date)} — ${label}`}
            style={{
              width: 22, height: 22, borderRadius: 4, display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 10.5, fontFamily: "'IBM Plex Mono', monospace", fontWeight: 600,
              background: `${c}1F`, color: c, border: `1px solid ${c}4D`, flexShrink: 0,
            }}
          >
            {dayLabel(date)[0]}
          </div>
        );
      })}
    </div>
  );
}

export default function AttendanceDashboard({ rawData }) {
  const { weekdayRecordsAll, WEEKS, MONTHS, ALL_TEAMS } = useMemo(() => computeDerived(rawData), [rawData]);

  const [view, setView] = useState('main');
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

  function handleMonthChange(val) {
    setMonthFilter(val);
    setWeekIdx(-1);
  }

  function handleTeamClick(t) {
    setTeam(t === team ? 'All teams' : t);
  }

  const trendData = useMemo(() => {
    return WEEKS.map((w) => {
      const recs = teamFiltered.filter((r) => w.dates.includes(r.date) && dayStatus(r) !== 'exempt');
      const present = recs.filter((r) => r.present).length;
      const unauthorized = recs.filter((r) => dayStatus(r) === 'unauthorized').length;
      const rate = recs.length ? Math.round((present / recs.length) * 1000) / 10 : 0;
      const unauthRate = recs.length ? Math.round((unauthorized / recs.length) * 1000) / 10 : 0;
      return { label: w.label, rate, unauthRate };
    });
  }, [teamFiltered, WEEKS]);

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

  const chartData = useMemo(() => {
    if (!isAggregate) {
      return scopeDates.map((date) => {
        const dayRecs = scopeRecords.filter((r) => r.date === date);
        const present = dayRecs.filter((r) => dayStatus(r) === 'present').length;
        const exempt = dayRecs.filter((r) => dayStatus(r) === 'exempt').length;
        const approved = dayRecs.filter((r) => dayStatus(r) === 'approved').length;
        const unauthorized = dayRecs.filter((r) => dayStatus(r) === 'unauthorized').length;
        const unverified = dayRecs.filter((r) => dayStatus(r) === 'unverified').length;
        return { label: dayLabel(date), present, exempt, approved, unauthorized, unverified, total: dayRecs.length };
      });
    }
    return visibleWeeks.map((w) => {
      const wRecs = scopeRecords.filter((r) => w.dates.includes(r.date));
      const present = wRecs.filter((r) => r.present).length;
      const exempt = wRecs.filter((r) => dayStatus(r) === 'exempt').length;
      const approved = wRecs.filter((r) => dayStatus(r) === 'approved').length;
      const unauthorized = wRecs.filter((r) => dayStatus(r) === 'unauthorized').length;
      const unverified = wRecs.filter((r) => dayStatus(r) === 'unverified').length;
      return { label: w.label, present, exempt, approved, unauthorized, unverified, total: wRecs.length };
    });
  }, [scopeRecords, isAggregate, scopeDates, visibleWeeks]);

  const employeeStats = useMemo(() => {
    const byId = {};
    scopeRecords.forEach((r) => {
      if (!byId[r.id]) byId[r.id] = { id: r.id, name: r.name, team: r.team, present: 0, exempt: 0, approved: 0, unauthorized: 0, unverified: 0, hours: 0, late: 0, early: 0, overtime: 0 };
      const e = byId[r.id];
      const status = dayStatus(r);
      if (status === 'present') { e.present += 1; e.hours += r.hours; e.overtime += r.overtime; }
      else if (status === 'exempt') e.exempt += 1;
      else if (status === 'approved') e.approved += 1;
      else if (status === 'unauthorized') e.unauthorized += 1;
      else e.unverified += 1;
      if (r.late) e.late += 1;
      if (r.early) e.early += 1;
    });
    return Object.values(byId).map((e) => ({
      ...e,
      absences: e.approved + e.unauthorized + e.unverified,
      avgHours: e.present ? Math.round((e.hours / e.present) * 10) / 10 : 0,
    }));
  }, [scopeRecords]);

  const teamStats = useMemo(() => {
    const byTeam = {};
    const dateSet = new Set(scopeDates);
    const base = weekdayRecordsAll.filter((r) => dateSet.has(r.date));
    base.forEach((r) => {
      if (!byTeam[r.team]) byTeam[r.team] = { team: r.team, present: 0, unauthorized: 0, total: 0, ids: new Set() };
      byTeam[r.team].ids.add(r.id);
      const status = dayStatus(r);
      if (status === 'exempt') return;
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
  const totalExempt = employeeStats.reduce((s, e) => s + e.exempt, 0);
  const chronicList = useMemo(() => employeeStats.filter((e) => e.unauthorized >= 3).sort((a, b) => b.unauthorized - a.unauthorized), [employeeStats]);
  const chronicCount = chronicList.length;

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

  return (
    <div style={{
      background: colors.paper, color: colors.ink, minHeight: '100%',
      fontFamily: "'IBM Plex Sans', 'Helvetica Neue', Arial, sans-serif",
      padding: '32px 28px 48px', boxSizing: 'border-box',
    }}>
      <div style={{ maxWidth: 1080, margin: '0 auto' }}>

        <header style={{ marginBottom: 28, borderBottom: `1px solid ${colors.line}`, paddingBottom: 20, textAlign: 'center' }}>
          <h1 style={{ fontFamily: "'Fraunces', Georgia, serif", fontWeight: 700, fontSize: 32, margin: 0, lineHeight: 1.2 }}>
            Microsoft Engineering Attendance Dashboard
          </h1>
        </header>

        {view === 'absentees' ? (
          <section>
            <button onClick={() => setView('main')} style={{ fontFamily: 'inherit', fontSize: 13, color: colors.muted, background: 'none', border: 'none', cursor: 'pointer', padding: 0, marginBottom: 18, display: 'flex', alignItems: 'center', gap: 6 }}>&larr; Back to dashboard</button>
            <h2 style={{ fontSize: 20, fontWeight: 600, margin: '0 0 4px', fontFamily: "'Fraunces', Georgia, serif" }}>Chronic unauthorized absence <span style={{ color: colors.muted, fontWeight: 400, fontSize: 15 }}>&middot; {scopeLabel}{team !== 'All teams' && ` · ${team}`}</span></h2>
            <div style={{ fontSize: 13, color: colors.muted, marginBottom: 8 }}>{chronicCount} employee{chronicCount === 1 ? '' : 's'} with 3 or more days in this view absent and with no leave on record. Employees on an approved WFH/maternity/onsite arrangement are excluded from this list by design.</div>
            <div style={{ display: 'flex', gap: 14, fontSize: 12, color: colors.muted, marginBottom: 20, flexWrap: 'wrap' }}>
              <span><span style={{ display: 'inline-block', width: 9, height: 9, borderRadius: 2, background: colors.good, marginRight: 5 }} />Present</span>
              <span><span style={{ display: 'inline-block', width: 9, height: 9, borderRadius: 2, background: colors.exempt, marginRight: 5 }} />Approved arrangement</span>
              <span><span style={{ display: 'inline-block', width: 9, height: 9, borderRadius: 2, background: colors.warn, marginRight: 5 }} />On approved leave</span>
              <span><span style={{ display: 'inline-block', width: 9, height: 9, borderRadius: 2, background: colors.alert, marginRight: 5 }} />No leave on record</span>
              <span><span style={{ display: 'inline-block', width: 9, height: 9, borderRadius: 2, background: colors.neutral, marginRight: 5 }} />No leave data available</span>
            </div>
            <div style={{ border: `1px solid ${colors.line}`, borderRadius: 4, overflow: 'hidden', background: colors.panel }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead><tr><th style={{ textAlign: 'left', padding: '10px 16px', color: colors.muted, fontWeight: 500, fontSize: 12 }}>Name</th><th style={{ textAlign: 'left', padding: '10px 16px', color: colors.muted, fontWeight: 500, fontSize: 12 }}>Team</th><th style={{ textAlign: 'left', padding: '10px 16px', color: colors.muted, fontWeight: 500, fontSize: 12 }}>{scopeLabel}</th><th style={{ textAlign: 'right', padding: '10px 16px', color: colors.muted, fontWeight: 500, fontSize: 12 }}>Unauthorized</th></tr></thead>
                <tbody>
                  {chronicList.map((e, i) => (
                    <tr key={e.id} style={{ borderTop: `1px solid ${colors.line}`, background: i % 2 ? 'rgba(0,0,0,0.015)' : 'transparent' }}>
                      <td style={{ padding: '10px 16px', fontWeight: 500 }}>{e.name}<span style={{ color: colors.muted, fontFamily: "'IBM Plex Mono', monospace", fontSize: 11.5, marginLeft: 8 }}>{e.id}</span></td>
                      <td style={{ padding: '10px 16px', fontSize: 12.5 }}>{e.team}</td>
                      <td style={{ padding: '10px 16px' }}><DayChips empId={e.id} dates={scopeDates} weekdayRecordsAll={weekdayRecordsAll} /></td>
                      <td style={{ padding: '10px 16px', textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace", color: colors.alert }}>{e.unauthorized}</td>
                    </tr>
                  ))}
                  {chronicList.length === 0 && (<tr><td colSpan={4} style={{ padding: '24px 16px', textAlign: 'center', color: colors.muted }}>No one crossed the 3-day unauthorized-absence threshold in this view.</td></tr>)}
                </tbody>
              </table>
            </div>
          </section>
        ) : (
          <>
            <section style={{ marginBottom: 24 }}>
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

            <section style={{ display: 'flex', flexWrap: 'wrap', gap: 0, marginBottom: 8, border: `1px solid ${colors.line}`, borderRadius: 4, overflow: 'hidden', background: colors.panel }}>
              {[
                { label: 'Headcount', value: totalEmployees, suffix: '' },
                { label: 'Attendance rate', value: attendanceRate, suffix: '%', tone: attendanceRate < 75 ? colors.alert : colors.good },
                { label: 'Avg hours / present day', value: avgHoursAll.toFixed(1), suffix: 'h' },
                { label: 'Unauthorized absences', value: totalUnauthorized, suffix: '', tone: totalUnauthorized > 0 ? colors.alert : colors.good },
                { label: 'Chronic (3+ unauthorized)', value: chronicCount, suffix: '', tone: chronicCount > 0 ? colors.alert : colors.good, clickable: true },
              ].map((stat, i) => (
                <div key={i} onClick={stat.clickable && chronicCount > 0 ? () => setView('absentees') : undefined} style={{ flex: '1 1 160px', padding: '18px 20px', borderRight: i < 4 ? `1px solid ${colors.line}` : 'none', cursor: stat.clickable && chronicCount > 0 ? 'pointer' : 'default' }}>
                  <div style={{ fontSize: 12.5, color: colors.muted, marginBottom: 8 }}>{stat.label}{stat.clickable && chronicCount > 0 && <span style={{ marginLeft: 5, textDecoration: 'underline dotted' }}>view</span>}</div>
                  <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 26, fontWeight: 500, color: stat.tone || colors.ink }}>{stat.value}{stat.suffix}</div>
                </div>
              ))}
            </section>
            <div style={{ fontSize: 12, color: colors.muted, marginBottom: 4 }}>Figures above reflect: <strong style={{ color: colors.ink }}>{scopeLabel}</strong>{team !== 'All teams' && ` · ${team}`}</div>
            {totalExempt > 0 && (<div style={{ fontSize: 12, color: colors.exempt, marginBottom: 32 }}>{totalExempt} absence-day{totalExempt === 1 ? '' : 's'} under an approved WFH/maternity/onsite arrangement excluded from the figures above.</div>)}
            {totalExempt === 0 && <div style={{ marginBottom: 32 }} />}

            <section style={{ marginBottom: 36 }}>
              <h2 style={{ fontSize: 16, fontWeight: 600, margin: '0 0 14px' }}>Attendance by team <span style={{ color: colors.muted, fontWeight: 400 }}>&middot; {scopeLabel}</span></h2>
              <div style={{ border: `1px solid ${colors.line}`, borderRadius: 4, overflow: 'hidden', background: colors.panel }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                  <thead><tr><th style={{ textAlign: 'left', padding: '10px 16px', color: colors.muted, fontWeight: 500, fontSize: 12 }}>Team</th><th style={{ textAlign: 'right', padding: '10px 16px', color: colors.muted, fontWeight: 500, fontSize: 12 }}>Headcount</th><th style={{ textAlign: 'right', padding: '10px 16px', color: colors.muted, fontWeight: 500, fontSize: 12 }}>Attendance rate</th><th style={{ textAlign: 'right', padding: '10px 16px', color: colors.muted, fontWeight: 500, fontSize: 12 }}>Unauthorized rate</th></tr></thead>
                  <tbody>
                    {teamStats.map((t, i) => {
                      const isSelected = t.team === team;
                      return (
                        <tr key={t.team} onClick={() => handleTeamClick(t.team)} style={{ borderTop: `1px solid ${colors.line}`, cursor: 'pointer', borderLeft: isSelected ? `3px solid ${colors.select}` : '3px solid transparent', background: isSelected ? `${colors.select}22` : (i % 2 ? 'rgba(0,0,0,0.015)' : 'transparent') }}>
                          <td style={{ padding: '9px 16px', fontWeight: isSelected ? 700 : 500, color: isSelected ? colors.select : colors.ink }}>{t.team}</td>
                          <td style={{ padding: '9px 16px', textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{t.headcount}</td>
                          <td style={{ padding: '9px 16px', textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace", color: t.rate < 60 ? colors.alert : t.rate < 80 ? colors.warn : colors.good }}>{t.rate}%</td>
                          <td style={{ padding: '9px 16px', textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace", color: t.unauthRate > 15 ? colors.alert : colors.ink }}>{t.unauthRate}%</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <div style={{ fontSize: 12, color: colors.muted, marginTop: 10 }}>Click a row to filter everything on this page to that team. Rates exclude any approved-arrangement absence-days.</div>
            </section>

            <section style={{ marginBottom: 36 }}>
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
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                      <thead><tr style={{ position: 'sticky', top: 0, background: colors.panel }}><th style={{ textAlign: 'left', padding: '8px 16px', color: colors.muted, fontWeight: 500, fontSize: 12 }}>Day</th><th style={{ textAlign: 'left', padding: '8px 16px', color: colors.muted, fontWeight: 500, fontSize: 12 }}>Date</th><th style={{ textAlign: 'left', padding: '8px 16px', color: colors.muted, fontWeight: 500, fontSize: 12 }}>Status</th><th style={{ textAlign: 'right', padding: '8px 16px', color: colors.muted, fontWeight: 500, fontSize: 12 }}>In</th><th style={{ textAlign: 'right', padding: '8px 16px', color: colors.muted, fontWeight: 500, fontSize: 12 }}>Out</th><th style={{ textAlign: 'right', padding: '8px 16px', color: colors.muted, fontWeight: 500, fontSize: 12 }}>Hours</th></tr></thead>
                      <tbody>
                        {scopeDates.map((date, i) => {
                          const rec = weekdayRecordsAll.find((r) => r.id === displayedMatch.id && r.date === date);
                          const status = rec ? dayStatus(rec) : 'unverified';
                          const c = STATUS_COLOR[status];
                          const label = rec && status === 'exempt' ? rec.exemption : (rec && rec.leave ? rec.leave : STATUS_LABEL[status]);
                          return (
                            <tr key={date} style={{ borderTop: `1px solid ${colors.line}`, background: i % 2 ? 'rgba(0,0,0,0.015)' : 'transparent' }}>
                              <td style={{ padding: '8px 16px', fontWeight: 500 }}>{dayLabel(date)}</td>
                              <td style={{ padding: '8px 16px', color: colors.muted }}>{shortDate(date)}</td>
                              <td style={{ padding: '8px 16px', color: c, fontWeight: 500 }}>{label}</td>
                              <td style={{ padding: '8px 16px', textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{rec && rec.inTime ? rec.inTime : '—'}</td>
                              <td style={{ padding: '8px 16px', textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{rec && rec.outTime ? rec.outTime : '—'}</td>
                              <td style={{ padding: '8px 16px', textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{rec && rec.hours ? rec.hours.toFixed(1) : '—'}</td>
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
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                    <thead><tr style={{ position: 'sticky', top: 0, background: colors.panel, boxShadow: `0 1px 0 ${colors.line}` }}>{[['name', 'Name'], ['team', 'Team'], ['present', 'Present'], ['exempt', 'Exempt'], ['approved', 'Approved leave'], ['unauthorized', 'No record'], ['avgHours', 'Avg hrs/day'], ['overtime', 'OT hrs']].map(([key, label]) => (<th key={key} onClick={() => toggleSort(key)} style={{ textAlign: (key === 'name' || key === 'team') ? 'left' : 'right', padding: '10px 16px', cursor: 'pointer', color: colors.muted, fontWeight: 500, fontSize: 12, userSelect: 'none' }}>{label}{sortKey === key ? (sortDir === 'asc' ? ' ↑' : ' ↓') : ''}</th>))}</tr></thead>
                    <tbody>
                      {filtered.map((e, i) => {
                        const isSelected = e.id === selectedEmpId;
                        return (
                          <tr key={e.id} onClick={() => setSelectedEmpId(isSelected ? null : e.id)} style={{ borderTop: `1px solid ${colors.line}`, cursor: 'pointer', borderLeft: isSelected ? `3px solid ${colors.select}` : (e.unauthorized >= 3 ? `3px solid ${colors.alert}` : (e.exempt > 0 ? `3px solid ${colors.exempt}` : '3px solid transparent')), background: isSelected ? `${colors.select}22` : (i % 2 ? 'rgba(0,0,0,0.015)' : 'transparent') }}>
                            <td style={{ padding: '9px 16px', fontWeight: isSelected ? 700 : 500, color: isSelected ? colors.select : colors.ink }}>{e.name}<span style={{ color: colors.muted, fontFamily: "'IBM Plex Mono', monospace", fontSize: 11.5, marginLeft: 8, fontWeight: 400 }}>{e.id}</span></td>
                            <td style={{ padding: '9px 16px', fontSize: 12.5 }}>{e.team}</td>
                            <td style={{ padding: '9px 16px', textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{e.present} / {scopeDates.length}</td>
                            <td style={{ padding: '9px 16px', textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace", color: colors.exempt }}>{e.exempt || '—'}</td>
                            <td style={{ padding: '9px 16px', textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace", color: colors.warn }}>{e.approved || '—'}</td>
                            <td style={{ padding: '9px 16px', textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace", color: e.unauthorized >= 3 ? colors.alert : colors.ink }}>{e.unauthorized || '—'}</td>
                            <td style={{ padding: '9px 16px', textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{e.avgHours || '—'}</td>
                            <td style={{ padding: '9px 16px', textAlign: 'right', fontFamily: "'IBM Plex Mono', monospace" }}>{e.overtime ? e.overtime.toFixed(1) : '—'}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
              <div style={{ fontSize: 12, color: colors.muted, marginTop: 10 }}>{filtered.length} of {totalEmployees} employees shown. Click a row to pin it above. "Exempt" days (purple margin) are excluded from the attendance-rate and unauthorized-absence figures. "No record" counts absences with no leave filed for employees whose leave data is available; rows with 3+ are flagged in the margin.</div>
            </section>

            <section style={{ marginBottom: 36 }}>
              <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 14, flexWrap: 'wrap', gap: 8 }}>
                <h2 style={{ fontSize: 16, fontWeight: 600, margin: 0 }}>Attendance &amp; unauthorized-absence rate, week over week {team !== 'All teams' && <span style={{ color: colors.muted, fontWeight: 400 }}>&middot; {team}</span>}</h2>
              </div>
              <div style={{ background: colors.panel, border: `1px solid ${colors.line}`, borderRadius: 4, padding: '16px 20px 4px' }}>
                <ResponsiveContainer width="100%" height={200}>
                  <LineChart data={trendData} margin={{ top: 4, right: 16, left: -12, bottom: 4 }}>
                    <CartesianGrid strokeDasharray="2 4" stroke={colors.line} vertical={false} />
                    <XAxis dataKey="label" tick={{ fontSize: 12, fill: colors.muted }} axisLine={{ stroke: colors.line }} tickLine={false} />
                    <YAxis tick={{ fontSize: 12, fill: colors.muted }} axisLine={false} tickLine={false} domain={[0, 100]} />
                    <Tooltip contentStyle={{ border: `1px solid ${colors.line}`, borderRadius: 4, fontSize: 12.5 }} formatter={(val, name) => [val + '%', name === 'rate' ? 'Attendance rate' : 'Unauthorized-absence rate']} />
                    <Line type="monotone" dataKey="rate" stroke={colors.good} strokeWidth={2} dot={{ r: 4, fill: colors.good }} />
                    <Line type="monotone" dataKey="unauthRate" stroke={colors.alert} strokeWidth={2} dot={{ r: 4, fill: colors.alert }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <div style={{ display: 'flex', gap: 14, fontSize: 12, color: colors.muted, marginTop: 8 }}>
                <span><span style={{ display: 'inline-block', width: 18, height: 2, background: colors.good, marginRight: 5, verticalAlign: 'middle' }} />Attendance rate</span>
                <span><span style={{ display: 'inline-block', width: 18, height: 2, background: colors.alert, marginRight: 5, verticalAlign: 'middle' }} />Unauthorized-absence rate</span>
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
                    <Tooltip contentStyle={{ border: `1px solid ${colors.line}`, borderRadius: 4, fontSize: 12.5 }} formatter={(val, name) => [val, ({ present: 'Present', exempt: 'Approved arrangement', approved: 'Approved leave', unauthorized: 'No leave on record', unverified: 'No leave data' })[name]]} />
                    <Bar dataKey="present" stackId="a" fill={colors.good} />
                    <Bar dataKey="exempt" stackId="a" fill={colors.exempt} />
                    <Bar dataKey="approved" stackId="a" fill={colors.warn} />
                    <Bar dataKey="unauthorized" stackId="a" fill={colors.alert} />
                    <Bar dataKey="unverified" stackId="a" fill={colors.neutral} radius={[2, 2, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div style={{ display: 'flex', gap: 14, fontSize: 12, color: colors.muted, marginTop: 8, flexWrap: 'wrap' }}>
                <span><span style={{ display: 'inline-block', width: 9, height: 9, borderRadius: 2, background: colors.good, marginRight: 5 }} />Present</span>
                <span><span style={{ display: 'inline-block', width: 9, height: 9, borderRadius: 2, background: colors.exempt, marginRight: 5 }} />Approved arrangement</span>
                <span><span style={{ display: 'inline-block', width: 9, height: 9, borderRadius: 2, background: colors.warn, marginRight: 5 }} />On approved leave</span>
                <span><span style={{ display: 'inline-block', width: 9, height: 9, borderRadius: 2, background: colors.alert, marginRight: 5 }} />No leave on record</span>
                <span><span style={{ display: 'inline-block', width: 9, height: 9, borderRadius: 2, background: colors.neutral, marginRight: 5 }} />No leave data available</span>
              </div>
            </section>

          </>
        )}
      </div>
    </div>
  );
}
