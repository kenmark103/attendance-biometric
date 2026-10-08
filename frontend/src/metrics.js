// Attendance metrics — single source of truth for every number on the dashboard.
// Pure ESM, no JSX, no dependencies. Testable with `node --test`.
//
// Adapted from dashboard-redesign-spec §2 to what this repo actually has:
// - Rows come from the API (attendance_records + leave + holidays + wfh),
//   one row per (employee, date) that exists; missing dates mean no row.
// - Check-in = checkIn field, check-out = checkOut field (ingestion decision,
//   not recomputed here). Hours = source WorkTime (rec.hours).
// - WFH approvals count as present (approved presence override, pre-existing
//   behavior the spec doesn't cover).
// - leaveLoaded is range-aware (see leaveLoadedFor): our leave data covers
//   August 2026 only, so September/October scopes stay "No record".

export const TIME_ZONE = 'Africa/Nairobi';

export function todayNairobi(now = new Date()) {
  return new Intl.DateTimeFormat('en-CA', { timeZone: TIME_ZONE }).format(now); // YYYY-MM-DD
}

// Never `new Date('YYYY-MM-DD')` (UTC parsing bug): parse manually, weekday via UTC.
export function parseISO(s) {
  const [y, m, d] = String(s).slice(0, 10).split('-').map(Number);
  return { y, m, d };
}

export function dowISO(s) {
  const { y, m, d } = parseISO(s);
  return new Date(Date.UTC(y, m - 1, d)).getUTCDay(); // 0 = Sunday
}

export function isWeekendISO(s) {
  const d = dowISO(s);
  return d === 0 || d === 6;
}

export function isoOf(y, m, d) {
  const p = (n) => String(n).padStart(2, '0');
  return `${y}-${p(m)}-${p(d)}`;
}

export function addDaysISO(s, n) {
  const { y, m, d } = parseISO(s);
  const t = new Date(Date.UTC(y, m - 1, d) + n * 86400000);
  return isoOf(t.getUTCFullYear(), t.getUTCMonth() + 1, t.getUTCDate());
}

export function datesBetween(a, b) {
  const out = [];
  if (!a || !b || a > b) return out;
  let cur = a;
  for (let i = 0; i < 2500 && cur <= b; i++) {
    out.push(cur);
    cur = addDaysISO(cur, 1);
  }
  return out;
}

const DAY2 = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'];
const DAY3 = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MON3 = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export function day2ISO(s) { return DAY2[dowISO(s)]; }
export function day3ISO(s) { return DAY3[dowISO(s)]; }
export function shortDateISO(s) {
  const { m, d } = parseISO(s);
  return `${MON3[m - 1]} ${d}`;
}
export function dayAndShortISO(s) {
  return `${day3ISO(s)} ${shortDateISO(s).split(' ')[1]}`;
}

// --- day status ------------------------------------------------------------

export function punchCount(rec) {
  return (rec.checkIn ? 1 : 0) + (rec.checkOut ? 1 : 0);
}

function hasApprovedLeave(rec) {
  return (rec.leaves || []).some((l) => (l.status || 'approved') === 'approved');
}

// Order follows the spec §2.2, with one documented adjudication: a past day
// with only a check-in (no check-out) is `missing_checkout`, not `present`
// — otherwise rule 6 would swallow rule 7 whole and test case 5 would fail.
export function classifyDay(rec, ctx) {
  if (isWeekendISO(rec.date)) return 'weekend';
  if (rec.isHoliday) return 'holiday';
  if (ctx.leaveLoaded && hasApprovedLeave(rec)) return 'leave';
  if (rec.wfh) return 'present';
  if (rec.date > ctx.today) return 'pending';
  const n = punchCount(rec);
  const isToday = rec.date === ctx.today;
  if (isToday && n === 0) return 'pending';
  if (isToday && n === 1) return 'in_progress';
  if (n >= 2) return rec.checkIn || rec.present ? 'present' : 'missing_checkout';
  if (n === 1) return 'missing_checkout';
  return 'no_record';
}

export function countsAsPresent(status) {
  return status === 'present' || status === 'missing_checkout';
}

export function countsInDenominator(status) {
  return status === 'present' || status === 'missing_checkout' || status === 'no_record';
}

// Check-out on a later calendar date than the attendance date.
export function outSuffix(rec) {
  if (rec.checkIn && rec.checkOut && rec.checkOut < rec.checkIn) return ' +1';
  return '';
}

// --- labels -----------------------------------------------------------------

export function statusLabel(status, leaveLoaded) {
  switch (status) {
    case 'present': return 'Present';
    case 'missing_checkout': return 'Missing check-out';
    case 'in_progress': return 'In progress';
    case 'pending': return 'Pending';
    case 'leave': return 'On leave';
    case 'weekend': return 'Weekend';
    case 'holiday': return 'Holiday';
    case 'no_record': return leaveLoaded ? 'Absent' : 'No record';
    default: return status;
  }
}

export function kpiLabels(leaveLoaded) {
  return leaveLoaded
    ? { count: 'Unauthorized absences', rate: 'Unauthorized rate' }
    : { count: 'No record (unreconciled)', rate: 'No-record rate' };
}

// --- aggregation --------------------------------------------------------------

// rows: API-shaped records in scope (any dates). dates: every calendar date in
// scope. roster: optional full employee list so zero-row staff are counted.
// Returns per-employee summaries + totals. Duplicate (employee, date) rows
// keep the one with more punches (API uniqueness makes this a dead branch).
export function aggregate(rows, dates, ctx, roster = []) {
  const byEmp = new Map();
  let duplicates = 0;
  for (const r of rows) {
    if (!byEmp.has(r.employeeId)) {
      byEmp.set(r.employeeId, { id: r.employeeId, name: r.name, team: r.team || 'Unassigned', byDate: new Map() });
    }
    const e = byEmp.get(r.employeeId);
    const prev = e.byDate.get(r.date);
    if (!prev || punchCount(r) > punchCount(prev)) {
      if (prev) duplicates += 1;
      e.byDate.set(r.date, r);
    } else if (prev) {
      duplicates += 1;
    }
  }
  for (const emp of roster) {
    if (!byEmp.has(emp.id)) {
      byEmp.set(emp.id, { id: emp.id, name: emp.name, team: emp.team || 'Unassigned', byDate: new Map() });
    }
  }
  if (duplicates > 0 && typeof console !== 'undefined') {
    console.warn(`[metrics] ${duplicates} duplicate employee-date rows; kept the one with more punches`);
  }

  const employees = [...byEmp.values()].map((e) => {
    let present = 0, expected = 0, noRecord = 0, missing = 0, leave = 0;
    let hoursSum = 0, hoursDays = 0, overtime = 0, late = 0, early = 0, offshift = 0, biometric = 0;
    let everPunchedWorkingPast = false;
    for (const d of dates) {
      const rec = e.byDate.get(d) || { date: d, leaves: [] };
      const st = classifyDay(rec, ctx);
      if (countsInDenominator(st)) expected += 1;
      if (countsAsPresent(st)) present += 1;
      if (st === 'no_record') noRecord += 1;
      if (st === 'missing_checkout') missing += 1;
      if (st === 'leave') leave += 1;
      if (st === 'present' || st === 'missing_checkout') {
        const n = punchCount(rec);
        if (n >= 2) {
          const h = Number(rec.hours ?? 0);
          if (h > 0) { hoursSum += h; hoursDays += 1; }
        }
        if (rec.source === 'biometric') biometric += 1;
        overtime += Number(rec.overtime ?? 0);
        if (rec.late) late += 1;
        if (rec.early) early += 1;
        if (rec.shiftAnomaly) offshift += 1;
      }
      if (d < ctx.today && !isWeekendISO(d) && !rec.isHoliday && punchCount(rec) > 0) {
        everPunchedWorkingPast = true;
      }
    }
    return {
      ...e,
      present, expected, noRecord, missing, leave,
      hours: Math.round(hoursSum * 10) / 10,
      hoursDays,
      avgHours: hoursDays ? Math.round((hoursSum / hoursDays) * 10) / 10 : 0,
      overtime: Math.round(overtime * 10) / 10,
      late, early, offshift, biometricDays: biometric,
      neverPunched: !everPunchedWorkingPast,
      attendanceRate: expected ? present / expected : null,
      noRecordRate: expected ? noRecord / expected : null,
    };
  });

  const inRates = ctx.excludeNeverPunched ? employees.filter((e) => !e.neverPunched) : employees;
  const expectedDays = inRates.reduce((s, e) => s + e.expected, 0);
  const presentDays = inRates.reduce((s, e) => s + e.present, 0);
  const noRecordDays = inRates.reduce((s, e) => s + e.noRecord, 0);
  const hoursSum = inRates.reduce((s, e) => s + e.hours, 0);
  const hoursDays = inRates.reduce((s, e) => s + e.hoursDays, 0);
  const biometricDays = inRates.reduce((s, e) => s + e.biometricDays, 0);
  return {
    employees,
    headcount: inRates.length,
    neverPunchedCount: employees.filter((e) => e.neverPunched).length,
    expectedDays,
    presentDays,
    noRecordDays,
    hoursSum: Math.round(hoursSum * 10) / 10,
    avgHours: hoursDays ? Math.round((hoursSum / hoursDays) * 10) / 10 : null,
    biometricDays,
    attendanceRate: expectedDays ? presentDays / expectedDays : null,
    noRecordRate: expectedDays ? noRecordDays / expectedDays : null,
  };
}

export function formatPct(x) {
  if (x === null || x === undefined || Number.isNaN(x)) return '—';
  const v = Math.round(x * 1000) / 10;
  return `${Number.isInteger(v) ? v : v.toFixed(1)}%`;
}

// --- slugs --------------------------------------------------------------------

export function teamSlug(name) {
  return String(name || 'unassigned').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').replace(/-+/g, '-');
}

// --- leaveLoaded ---------------------------------------------------------------
// True only when every in-scope month has leave data (leave_by_month from
// /stats/coverage). August-only data + September scope => false, which is
// exactly the "unreconciled" wording problem #1.
export function leaveLoadedFor(dates, leaveByMonth) {
  if (!dates.length) return false;
  const months = new Set(dates.map((d) => d.slice(0, 7)));
  const have = new Set(leaveByMonth || []);
  return [...months].every((m) => have.has(m));
}

// --- CSV ------------------------------------------------------------------------

export function toCSV(header, rows) {
  const esc = (v) => {
    const s = v === null || v === undefined ? '' : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return '﻿' + [header, ...rows].map((r) => r.map(esc).join(',')).join('\n');
}
