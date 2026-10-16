// Leave-calendar overlay cases (leave-ingestion spec §9, one per table row
// plus half-day, carry-forward and legacy-fallback cases).
// Fixture: today = 2026-10-08; test dates in Sept 2026 (all past).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  classifyDay, aggregate, dayWeight, carryRec, statusLabel,
  hasPunch, isBiometricCovered, datesBetween, leaveQuality,
} from '../src/metrics.js';
import { STATUS_COLORS, OVERLAY_LEGEND } from '../src/statusColors.js';

const TODAY = '2026-10-08';
// Sept 2026: Mon 7, Tue 8, Wed 9, Thu 10, Fri 11, Sat 12, Sun 13.
const MON = '2026-09-07';
const TUE = '2026-09-08';
const SAT = '2026-09-12';

const CTX = {
  today: TODAY, leaveLoaded: false, leaveActive: true,
  coverageThrough: '2026-09-30',
  coveredDates: ['2026-09-07', '2026-09-08', '2026-09-09', '2026-09-10', '2026-09-11', '2026-09-12'],
  trustZoho: true, calMeta: {},
};

function rec(employeeId, date, patch = {}) {
  return {
    employeeId, name: `Emp ${employeeId}`, team: 'Test',
    date, checkIn: null, checkOut: null, hours: 0, overtime: 0,
    late: false, early: false, present: false, leaves: [], isHoliday: false,
    dayKind: undefined, leaveType: null, leaveFraction: 1,
    zohoPresence: null, calendarSource: null, rawCode: null,
    ...patch,
  };
}

const PUNCH = { checkIn: '09:00', checkOut: '17:00', present: true, hours: 8 };

test('row 1: no calendar row — punch present, Sat weekend, otherwise absent_unverified', () => {
  assert.equal(classifyDay(rec('1', MON, PUNCH), CTX), 'present');
  assert.equal(classifyDay(rec('1', SAT), CTX), 'weekend');
  // Without a calendar row the day can never be a verified absence,
  // even when biometric data covers the date.
  assert.equal(classifyDay(rec('1', MON), CTX), 'absent_unverified');
  assert.equal(classifyDay(rec('1', MON), { ...CTX, coveredDates: [] }), 'absent_unverified');
});

test('row 2: not_employed excluded even with a punch', () => {
  assert.equal(classifyDay(rec('1', MON, { dayKind: 'not_employed' }), CTX), 'not_employed');
  assert.equal(classifyDay(rec('1', MON, { dayKind: 'not_employed', ...PUNCH }), CTX), 'not_employed');
  const agg = aggregate([rec('1', MON, { dayKind: 'not_employed' })], [MON], CTX);
  assert.equal(agg.expectedDays, 0);
  assert.equal(agg.notEmployedDays, 1);
});

test('rows 3-4: holiday/weekend with and without punches', () => {
  assert.equal(classifyDay(rec('1', MON, { dayKind: 'holiday' }), CTX), 'holiday');
  assert.equal(classifyDay(rec('1', MON, { dayKind: 'holiday', ...PUNCH }), CTX), 'worked_holiday');
  assert.equal(classifyDay(rec('1', SAT, { dayKind: 'weekend' }), CTX), 'weekend');
  assert.equal(classifyDay(rec('1', SAT, { dayKind: 'weekend', ...PUNCH }), CTX), 'worked_weekend');
});

test('row 5: on_duty counts present', () => {
  assert.equal(classifyDay(rec('1', MON, { dayKind: 'on_duty' }), CTX), 'on_duty');
  assert.deepEqual(dayWeight('on_duty', rec('1', MON)), { present: 1, expected: 1 });
});

test('row 6: full leave, conflict on punch or Zoho presence', () => {
  assert.equal(classifyDay(rec('1', MON, { dayKind: 'leave', leaveType: 'Annual Leave' }), CTX), 'leave');
  assert.equal(classifyDay(rec('1', MON, { dayKind: 'leave', ...PUNCH }), CTX), 'leave_conflict');
  assert.equal(classifyDay(rec('1', MON, { dayKind: 'leave', zohoPresence: true }), CTX), 'leave_conflict');
  const agg = aggregate([rec('1', MON, { dayKind: 'leave' })], [MON], CTX);
  assert.equal(agg.employees[0].leave, 1);
  assert.equal(agg.employees[0].leaveWorkdays, 1);
  assert.equal(agg.expectedDays, 0);
});

test('row 7: half leave splits the working portion', () => {
  const r = rec('1', MON, { dayKind: 'leave', leaveFraction: 0.5 });
  assert.equal(classifyDay(r, CTX), 'half_leave');
  assert.deepEqual(dayWeight('half_leave', { ...r, ...PUNCH }), { present: 0.5, expected: 0.5 });
  assert.deepEqual(dayWeight('half_leave', r), { present: 0, expected: 0.5, halfAbsent: true });
  const agg = aggregate([r], [MON], CTX);
  assert.equal(agg.presentDays, 0);
  assert.equal(agg.expectedDays, 0.5);
  assert.equal(agg.absentDays, 0.5);
});

test('row 8: working — punch, Zoho-only, absent, absent_unverified', () => {
  assert.equal(classifyDay(rec('1', MON, { dayKind: 'working', ...PUNCH }), CTX), 'present');
  assert.equal(classifyDay(rec('1', MON, { dayKind: 'working', zohoPresence: true }), CTX), 'present_zoho_only');
  assert.equal(classifyDay(rec('1', MON, { dayKind: 'working', zohoPresence: true }), { ...CTX, trustZoho: false }), 'absent');
  assert.equal(classifyDay(rec('1', MON, { dayKind: 'working' }), CTX), 'absent');
  assert.equal(classifyDay(rec('1', MON, { dayKind: 'working' }), { ...CTX, coveredDates: [] }), 'absent_unverified');
});

test('row 9: unknown kind is unverified, never absent', () => {
  assert.equal(classifyDay(rec('1', MON, { dayKind: 'unknown' }), CTX), 'unverified');
  const agg = aggregate([rec('1', MON, { dayKind: 'unknown' })], [MON], CTX);
  assert.equal(agg.expectedDays, 0);
  assert.equal(agg.unverifiedDays, 1);
});

test('carry-forward: trailing not_employed persists, else no-leave-data', () => {
  const meta = { 1: { lastDate: '2026-09-05', lastKind: 'not_employed' } };
  const ctx = { ...CTX, calMeta: meta };
  assert.equal(classifyDay(carryRec('1', MON, ctx), ctx), 'not_employed');
  const meta2 = { 1: { lastDate: '2026-09-05', lastKind: 'working' } };
  const ctx2 = { ...CTX, calMeta: meta2 };
  assert.equal(classifyDay(carryRec('1', MON, ctx2), ctx2), 'absent_unverified');
});

test('legacy path unchanged while no calendar coverage exists', () => {
  const legacy = { today: TODAY, leaveLoaded: false };
  assert.equal(classifyDay(rec('1', MON), legacy), 'no_record');
  assert.equal(classifyDay(rec('1', SAT, PUNCH), legacy), 'weekend');
});

test('helpers: hasPunch, isBiometricCovered, labels', () => {
  assert.equal(hasPunch(rec('1', MON, { present: true })), true);
  assert.equal(hasPunch(rec('1', MON)), false);
  assert.equal(isBiometricCovered(MON, CTX), true);
  assert.equal(isBiometricCovered(TUE, { ...CTX, coveredDates: new Set([TUE]) }), true);
  assert.equal(isBiometricCovered(MON, {}), false);
  assert.equal(statusLabel('present_zoho_only'), 'Present (Zoho only)');
  assert.equal(statusLabel('leave_conflict'), 'Leave conflict');
  assert.equal(statusLabel('half_leave'), 'Half leave');
  assert.equal(statusLabel('absent'), 'Absent');
  assert.equal(statusLabel('absent_unverified'), 'Absent (unverified)');
  assert.equal(statusLabel('unverified'), 'Unverified');
  assert.equal(statusLabel('not_employed'), 'Not employed');
});

test('mixed-week overlay rates', () => {
  const id = '9';
  const rows = [
    rec(id, '2026-09-07', { dayKind: 'working', ...PUNCH }),       // present
    rec(id, '2026-09-08', { dayKind: 'leave' }),                  // leave
    rec(id, '2026-09-09', { dayKind: 'working' }),                 // absent
    rec(id, '2026-09-10', { dayKind: 'working', zohoPresence: true }), // zoho only
    rec(id, '2026-09-11', { dayKind: 'leave', leaveFraction: 0.5, ...PUNCH }), // half+present
  ];
  const agg = aggregate(rows, datesBetween('2026-09-07', '2026-09-11'), CTX);
  const m = agg.employees[0];
  assert.equal(m.present, 2.5);
  assert.equal(m.expected, 3.5);
  assert.equal(m.absent, 1);
  assert.equal(m.leave, 1.5);
  assert.equal(m.leaveWorkdays, 1.5);
  assert.equal(m.zohoOnly, 1);
});

test('legend covers every overlay status', () => {
  const statuses = new Set([
    'present', 'missing_checkout', 'present_zoho_only', 'leave', 'leave_conflict',
    'half_leave', 'on_duty', 'absent', 'absent_unverified', 'unverified',
    'not_employed', 'weekend', 'worked_weekend', 'holiday', 'worked_holiday',
    'pending', 'in_progress', 'no_record',
  ]);
  for (const s of statuses) {
    assert.ok(STATUS_COLORS[s], `no colour for ${s}`);
    assert.notEqual(statusLabel(s, true), s, `no label for ${s}`);
  }
  for (const s of OVERLAY_LEGEND) assert.ok(STATUS_COLORS[s], `legend ${s} has no colour`);
});

test('leaveQuality summarises conflicts, unverified, gaps and disagreements', () => {
  const dates = datesBetween('2026-09-07', '2026-09-09'); // Mon-Wed
  const rows = [
    rec('1', '2026-09-07', { dayKind: 'leave', ...PUNCH, rawCode: 'EL/P' }),
    rec('1', '2026-09-08', { dayKind: 'working' }),
    rec('1', '2026-09-09', { dayKind: 'working', zohoPresence: true }),
    rec('2', '2026-09-07', { dayKind: 'working', zohoPresence: false, ...PUNCH }),
    rec('2', '2026-09-08', { dayKind: 'unknown' }),
    rec('2', '2026-09-09', { dayKind: 'working', zohoPresence: false, ...PUNCH }),
  ];
  const q = leaveQuality(rows, dates, CTX, [{ id: '1', name: 'Emp 1' }, { id: '2', name: 'Emp 2' }, { id: '3', name: 'Ghost' }]);
  assert.equal(q.conflictCount, 1);
  assert.equal(q.conflicts[0].employeeId, '1');
  // Unknown-code day (1) + ghost's three no-calendar days (rule 1).
  assert.equal(q.unverifiedDays, 4);
  assert.equal(q.unverifiedEmployees, 2);
  assert.deepEqual(q.noLeaveData, [{ id: '3', name: 'Ghost' }]);
  assert.equal(q.zohoOnly, 1);
  assert.equal(q.zohoAbsentPunch, 2);
  assert.equal(q.disagreements.length, 2);
});
