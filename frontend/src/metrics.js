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

export function hasPunch(rec) {
  return punchCount(rec) > 0 || !!rec.present;
}

export function isBiometricCovered(d, ctx) {
  const s = ctx.coveredDates;
  if (!s) return false;
  return typeof s.has === 'function' ? s.has(d) : s.includes(d);
}

// Punch mapping shared by every rule that treats a punch as presence:
// 2+ punches keep the legacy check-in/present nuance, a lone past punch is
// missing_checkout, a lone today punch is still in progress.
export function punchStatus(rec, ctx) {
  const n = punchCount(rec);
  if (n >= 2) return rec.checkIn || rec.present ? 'present' : 'missing_checkout';
  if (n === 1) return rec.date === ctx.today ? 'in_progress' : 'missing_checkout';
  return null;
}

// Synthesis for roster-only employees past their last calendar row
// (range-local carry-forward; api.js does the same for attendance rows).
export function carryRec(employeeId, date, ctx) {
  const base = { date, leaves: [] };
  if (employeeId) base.employeeId = employeeId;
  const meta = ctx.calMeta && employeeId ? ctx.calMeta[employeeId] : null;
  if (meta && date > meta.lastDate && meta.lastKind === 'not_employed') {
    base.dayKind = 'not_employed';
    base.carriedForward = true;
  }
  return base;
}

function hasApprovedLeave(rec) {
  return (rec.leaves || []).some((l) => (l.status || 'approved') === 'approved');
}

// Legacy classification: used verbatim while no leave-calendar coverage
// exists, so dashboard numbers are unchanged without leave data.
function classifyLegacy(rec, ctx) {
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

// Leave-calendar overlay (leave-ingestion spec §9). First match wins.
// `rec.dayKind` is the authoritative per-day kind (undefined = no calendar
// row, beyond coverage, or employee not in any covering import -> rule 1).
// Order follows the spec table, with weekend/holiday kept ahead of the
// today/pending handling so future dates keep their day-type label.
export function classifyDay(rec, ctx) {
  if (!ctx.leaveActive) return classifyLegacy(rec, ctx);
  const kind = rec.dayKind ?? null;
  const punch = hasPunch(rec);
  if (kind === 'not_employed') return 'not_employed';
  if (kind === 'holiday' || rec.isHoliday) return punch ? 'worked_holiday' : 'holiday';
  if (kind === 'weekend') return punch ? 'worked_weekend' : 'weekend';
  if (kind === null && isWeekendISO(rec.date)) {
    return punch ? punchStatus(rec, ctx) : 'weekend';
  }
  if (rec.wfh) return 'present';
  if (rec.date > ctx.today) return 'pending';
  if (rec.date === ctx.today) return punch ? punchStatus(rec, ctx) : 'pending';
  if (kind === 'leave' && (rec.leaveFraction ?? 1) === 1) {
    return (punch || rec.zohoPresence === true) ? 'leave_conflict' : 'leave';
  }
  if (kind === 'leave') return 'half_leave'; // fraction 0.5
  if (kind === 'on_duty') return 'on_duty';
  if (kind === 'working') {
    if (punch) return punchStatus(rec, ctx);
    if (rec.zohoPresence === true && ctx.trustZoho !== false) return 'present_zoho_only';
    return isBiometricCovered(rec.date, ctx) ? 'absent' : 'absent_unverified';
  }
  if (kind === 'unknown') return 'unverified';
  if (punch) return punchStatus(rec, ctx);
  return 'absent_unverified';
}

export function countsAsPresent(status) {
  return status === 'present' || status === 'missing_checkout'
    || status === 'present_zoho_only' || status === 'leave_conflict'
    || status === 'on_duty';
}

export function countsInDenominator(status) {
  return status === 'present' || status === 'missing_checkout'
    || status === 'no_record' || status === 'absent'
    || status === 'present_zoho_only' || status === 'leave_conflict'
    || status === 'on_duty';
}

// Fractional day weight for rates. Half leave contributes its 0.5 working
// portion to the denominator and to present (or absent) depending on
// whether a punch or Zoho presence backs it (spec §9 rows 6-8).
export function dayWeight(status, rec) {
  switch (status) {
    case 'present':
    case 'missing_checkout':
    case 'on_duty':
    case 'present_zoho_only':
    case 'leave_conflict':
      return { present: 1, expected: 1 };
    case 'half_leave':
      return (hasPunch(rec) || rec.zohoPresence === true)
        ? { present: 0.5, expected: 0.5 }
        : { present: 0, expected: 0.5, halfAbsent: true };
    case 'absent':
    case 'no_record':
      return { present: 0, expected: 1 };
    default:
      return { present: 0, expected: 0 };
  }
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
    case 'leave_conflict': return 'Leave conflict';
    case 'half_leave': return 'Half leave';
    case 'on_duty': return 'On duty';
    case 'present_zoho_only': return 'Present (Zoho only)';
    case 'worked_holiday': return 'Worked holiday';
    case 'worked_weekend': return 'Worked weekend';
    case 'not_employed': return 'Not employed';
    case 'absent': return 'Absent';
    case 'absent_unverified': return 'Absent (unverified)';
    case 'unverified': return 'Unverified';
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
    let absent = 0, absentUnverified = 0, unverified = 0, notEmployed = 0;
    let leaveWorkdays = 0, conflicts = 0, zohoOnly = 0;
    let hoursSum = 0, hoursDays = 0, overtime = 0, late = 0, early = 0, offshift = 0, biometric = 0;
    let everPunchedWorkingPast = false;
    for (const d of dates) {
      const rec = e.byDate.get(d) || carryRec(e.id, d, ctx);
      const st = classifyDay(rec, ctx);
      const w = dayWeight(st, rec);
      expected += w.expected;
      present += w.present;
      if (st === 'no_record') noRecord += 1;
      if (st === 'absent' || w.halfAbsent) absent += w.halfAbsent ? 0.5 : 1;
      if (st === 'absent_unverified') absentUnverified += 1;
      if (st === 'unverified') unverified += 1;
      if (st === 'not_employed') notEmployed += 1;
      if (st === 'missing_checkout') missing += 1;
      if (st === 'leave' || st === 'half_leave') {
        const portion = st === 'half_leave' ? 0.5 : 1;
        leave += portion;
        if (!isWeekendISO(d)) leaveWorkdays += portion;
      }
      if (st === 'leave_conflict') conflicts += 1;
      if (st === 'present_zoho_only') zohoOnly += 1;
      if (w.present > 0) {
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
      absent, absentUnverified, unverifiedCount: unverified, notEmployed,
      leaveWorkdays, conflicts, zohoOnly,
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
  const absentDays = inRates.reduce((s, e) => s + e.absent, 0);
  const unverifiedDays = inRates.reduce((s, e) => s + e.absentUnverified + e.unverifiedCount, 0);
  const notEmployedDays = inRates.reduce((s, e) => s + e.notEmployed, 0);
  const leaveWorkdays = inRates.reduce((s, e) => s + e.leaveWorkdays, 0);
  const conflictDays = inRates.reduce((s, e) => s + e.conflicts, 0);
  const zohoOnlyDays = inRates.reduce((s, e) => s + e.zohoOnly, 0);
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
    absentDays,
    unverifiedDays,
    notEmployedDays,
    leaveWorkdays,
    conflictDays,
    zohoOnlyDays,
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

// --- leave data quality -------------------------------------------------------
// Pure summary for the Data health quality panel (spec §11): leave days
// worked, unverified days, employees with no leave data, and Zoho-vs-
// biometric disagreements. Counts are scope-local; samples cap at 5.
export function leaveQuality(rows, dates, ctx, roster = []) {
  const inScope = new Set(dates);
  const byEmp = new Map();
  const nameOf = new Map(roster.map((e) => [e.id, e.name]));
  for (const r of rows) {
    if (!inScope.has(r.date)) continue;
    if (!byEmp.has(r.employeeId)) {
      byEmp.set(r.employeeId, { id: r.employeeId, name: r.name, days: new Map() });
    }
    byEmp.get(r.employeeId).days.set(r.date, r);
    if (!nameOf.has(r.employeeId)) nameOf.set(r.employeeId, r.name);
  }
  for (const emp of roster) {
    if (!byEmp.has(emp.id)) byEmp.set(emp.id, { id: emp.id, name: emp.name, days: new Map() });
  }
  const conflicts = [];
  const unverifiedTop = new Map();
  const disagreements = [];
  let unverifiedDays = 0, zohoOnly = 0, zohoAbsentPunch = 0;
  const noLeaveData = [];
  for (const e of byEmp.values()) {
    let indexed = 0;
    let empUnverified = 0;
    for (const d of dates) {
      const rec = e.days.get(d) || carryRec(e.id, d, ctx);
      if (rec.dayKind !== undefined && rec.dayKind !== null) indexed += 1;
      const st = classifyDay(rec, ctx);
      if (st === 'leave_conflict') {
        conflicts.push({ employeeId: e.id, name: e.name, date: d, rawCode: rec.rawCode || null });
      }
      if (st === 'absent_unverified' || st === 'unverified') {
        unverifiedDays += 1;
        empUnverified += 1;
      }
      const punched = hasPunch(rec);
      if (rec.zohoPresence === true && !punched) zohoOnly += 1;
      if (rec.zohoPresence === false && punched && rec.dayKind === 'working') {
        zohoAbsentPunch += 1;
        if (disagreements.length < 5) {
          disagreements.push({ employeeId: e.id, name: e.name, date: d, rawCode: rec.rawCode || null });
        }
      }
    }
    if (empUnverified > 0) unverifiedTop.set(e.id, { employeeId: e.id, name: e.name, days: empUnverified });
    if (indexed === 0) noLeaveData.push({ id: e.id, name: e.name });
  }
  const top = [...unverifiedTop.values()].sort((a, b) => b.days - a.days).slice(0, 5);
  return {
    conflictCount: conflicts.length,
    conflicts: conflicts.slice(0, 5),
    unverifiedDays,
    unverifiedTop: top,
    unverifiedEmployees: unverifiedTop.size,
    noLeaveData,
    zohoOnly,
    zohoAbsentPunch,
    disagreements,
  };
}

// --- CSV ------------------------------------------------------------------------

export function toCSV(header, rows) {
  const esc = (v) => {
    const s = v === null || v === undefined ? '' : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return '﻿' + [header, ...rows].map((r) => r.map(esc).join(',')).join('\n');
}
