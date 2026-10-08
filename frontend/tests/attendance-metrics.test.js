// Phase 1 acceptance cases from dashboard-redesign-spec §12.
// Fixture: today = 2026-10-08, range 2026-10-01..2026-10-08, no holidays.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  classifyDay, aggregate, statusLabel, kpiLabels, formatPct,
  teamSlug, leaveLoadedFor, datesBetween, todayNairobi,
} from '../src/metrics.js';

const TODAY = '2026-10-08';
const DATES = datesBetween('2026-10-01', '2026-10-08');
const CTX = { today: TODAY, leaveLoaded: false };

function rec(employeeId, date, patch = {}) {
  return {
    employeeId, name: `Emp ${employeeId}`, team: 'Test',
    date, checkIn: null, checkOut: null, hours: 0, overtime: 0,
    late: false, early: false, present: false, leaves: [], isHoliday: false,
    ...patch,
  };
}

test('1: Oct 3 and Oct 4 are weekend for everyone, excluded from denominators', () => {
  for (const d of ['2026-10-03', '2026-10-04']) {
    assert.equal(classifyDay(rec('1', d, { checkIn: '09:00', checkOut: '17:00', present: true }), CTX), 'weekend');
  }
  const agg = aggregate([rec('1', '2026-10-01', { checkIn: '09:00', checkOut: '17:00', present: true, hours: 8 })], ['2026-10-03', '2026-10-04'], CTX);
  assert.equal(agg.expectedDays, 0);
  assert.equal(agg.attendanceRate, null);
  assert.equal(formatPct(agg.attendanceRate), '—');
});

test('2: Martha (13537) full-week statuses and rates', () => {
  const id = '13537';
  const rows = [
    rec(id, '2026-10-06', { checkIn: '09:52', checkOut: '17:01', present: true, hours: 7.2 }),
    rec(id, '2026-10-07', { checkIn: '09:53', checkOut: '13:14', present: true, hours: 3.4 }),
    rec(id, '2026-10-08', { checkIn: '12:14', present: true }),
  ];
  const got = {};
  for (const d of DATES) {
    got[d] = classifyDay(rows.find((r) => r.date === d) || rec(id, d), CTX);
  }
  assert.deepEqual(got, {
    '2026-10-01': 'no_record',
    '2026-10-02': 'no_record',
    '2026-10-03': 'weekend',
    '2026-10-04': 'weekend',
    '2026-10-05': 'no_record',
    '2026-10-06': 'present',
    '2026-10-07': 'present',
    '2026-10-08': 'in_progress',
  });
  const agg = aggregate(rows, DATES, CTX);
  const m = agg.employees[0];
  assert.equal(m.present, 2);
  assert.equal(m.expected, 5);
  assert.equal(agg.attendanceRate, 0.4);
  assert.equal(agg.noRecordRate, 0.6);
  assert.equal(formatPct(agg.attendanceRate), '40%');
  assert.equal(m.avgHours, 5.3);
});

test('3: employee with no rows at all stays in rates as neverPunched', () => {
  const agg = aggregate([], datesBetween('2026-10-01', '2026-10-07'), CTX,
    [{ id: 'ghost', name: 'Ghost', team: 'Test' }]);
  const m = agg.employees[0];
  assert.equal(m.neverPunched, true);
  assert.equal(m.present, 0);
  assert.equal(m.expected, 5);
  assert.equal(m.noRecord, 5);
  assert.equal(agg.headcount, 1);
});

test('4: today with no punch is pending, excluded from denominator', () => {
  assert.equal(classifyDay(rec('1', TODAY), CTX), 'pending');
  const agg = aggregate([], [TODAY], CTX);
  assert.equal(agg.expectedDays, 0);
});

test('5: past weekday with one punch only is missing_checkout (present + exception)', () => {
  const st = classifyDay(rec('1', '2026-10-06', { checkIn: '09:52', present: true }), CTX);
  assert.equal(st, 'missing_checkout');
  const agg = aggregate([rec('1', '2026-10-06', { checkIn: '09:52', present: true })], ['2026-10-06'], CTX);
  assert.equal(agg.presentDays, 1);
  assert.equal(agg.expectedDays, 1);
  assert.equal(agg.employees[0].missing, 1);
});

test('6: night shift keeps ProcessDate, out shows +1, hours from WorkTime', async () => {
  const { outSuffix } = await import('../src/metrics.js');
  const r = rec('1', '2026-10-06', { checkIn: '18:05', checkOut: '02:10', present: true, hours: 8.1 });
  assert.equal(classifyDay(r, CTX), 'present');
  assert.equal(outSuffix(r), ' +1');
  const agg = aggregate([r], ['2026-10-06'], CTX);
  assert.equal(agg.employees[0].avgHours, 8.1);
});

test('7: 2-member team, one present one absent => 50%, small team', () => {
  const rows = [
    rec('a', '2026-10-06', { checkIn: '09:00', checkOut: '17:00', present: true, hours: 8 }),
    rec('a', '2026-10-07', { checkIn: '09:00', checkOut: '17:00', present: true, hours: 8 }),
  ];
  const agg = aggregate(rows, ['2026-10-06', '2026-10-07'], CTX,
    [{ id: 'b', name: 'B', team: 'Test' }]);
  assert.equal(agg.attendanceRate, 0.5);
  assert.equal(agg.headcount, 2);
  assert.ok(agg.headcount < 5); // small-team marker threshold
});

test('8: empty employee set gives null rates rendered as em dash', () => {
  const agg = aggregate([], ['2026-10-06'], CTX);
  assert.equal(agg.attendanceRate, null);
  assert.equal(formatPct(agg.attendanceRate), '—');
});

test('9: labels switch on leaveLoaded, Unauthorized never leaks', () => {
  assert.equal(statusLabel('no_record', false), 'No record');
  assert.equal(statusLabel('no_record', true), 'Absent');
  assert.equal(kpiLabels(false).count, 'No record (unreconciled)');
  assert.equal(kpiLabels(true).count, 'Unauthorized absences');
  assert.ok(!JSON.stringify(kpiLabels(false)).includes('nauthorized'));
});

test('10: team slugs', () => {
  assert.equal(teamSlug('O365 Privacy Manual Testing'), 'o365-privacy-manual-testing');
  assert.equal(teamSlug('SEManTEX'), 'semantex');
});

test('11: nopunch=exclude drops the never-punched employee', () => {
  const rows = [rec('a', '2026-10-06', { checkIn: '09:00', checkOut: '17:00', present: true, hours: 8 })];
  const roster = [{ id: 'b', name: 'B', team: 'Test' }];
  const dates = ['2026-10-06'];
  const incl = aggregate(rows, dates, { ...CTX, excludeNeverPunched: false }, roster);
  const excl = aggregate(rows, dates, { ...CTX, excludeNeverPunched: true }, roster);
  assert.equal(incl.headcount, 2);
  assert.equal(excl.headcount, 1);
  assert.equal(excl.neverPunchedCount, 1);
  assert.equal(excl.expectedDays, 1);
});

test('12: duplicate employee-date rows keep the one with more punches', () => {
  const rows = [
    rec('1', '2026-10-06', { checkIn: '09:00', present: true }),
    rec('1', '2026-10-06', { checkIn: '09:00', checkOut: '17:00', present: true, hours: 8 }),
  ];
  const agg = aggregate(rows, ['2026-10-06'], CTX);
  assert.equal(agg.employees[0].avgHours, 8);
});

test('leaveLoadedFor: August scope true, September scope false, mixed false', () => {
  assert.equal(leaveLoadedFor(['2026-08-03', '2026-08-04'], ['2026-08']), true);
  assert.equal(leaveLoadedFor(['2026-09-01'], ['2026-08']), false);
  assert.equal(leaveLoadedFor(['2026-08-31', '2026-09-01'], ['2026-08']), false);
});

test('todayNairobi returns YYYY-MM-DD', () => {
  assert.match(todayNairobi(new Date('2026-10-08T10:00:00Z')), /^\d{4}-\d{2}-\d{2}$/);
});
