import test from 'node:test';
import assert from 'node:assert/strict';
import { adaptMetrics } from '../src/metrics.js';

const API = {
  summary: {
    headcount: 3, attendance_rate: 0.7057, is_provisional: true,
    provisional_days: 2, no_data_days: 5, present_days: 10, on_leave_days: 3,
    absent_days: 4, unverified_days: 1, leave_conflict_days: 0,
    missing_checkouts: 2, no_punch_in_period: 1, avg_hours: 6.4, biometric_days: 7,
  },
  daily: [
    { date: '2026-09-01', state: 'covered', attendance_rate: 0.5, status_counts: { present: 2, on_leave: 1, absent: 1, unverified: 0 } },
    { date: '2026-09-02', state: 'provisional', attendance_rate: 0.25, status_counts: { present: 1, on_leave: 0, absent: 1, unverified: 2 } },
    { date: '2026-09-03', state: 'no_data', attendance_rate: null, status_counts: { present: 0, on_leave: 0, absent: 0, unverified: 0 } },
  ],
  employees: [
    { id: '1', name: 'A', team: 'Ops', shift: 'day', present: 2, expected: 3, on_leave: 0, no_record: 1, absent: 1, unverified: 0, missing: 0, leave_conflict: 0, never_punched: false, avg_hours: 7, hours: 14, overtime: 1.5, late: 0, early: 0, biometric_days: 2, attendance_rate: 0.6667, days: 3 },
  ],
  teams: [
    { team: 'Ops', headcount: 3, attendance_rate: 0.7057, present_days: 10, on_leave_days: 3, absent_days: 4, unverified_days: 1, missing_checkouts: 2, no_punch_in_period: 1, avg_hours: 6.4, is_provisional: true, provisional_days: 2, no_data_days: 5, small: false, daily: [] },
  ],
};

test('adaptMetrics: summary scalars pass through', () => {
  const m = adaptMetrics(API);
  assert.equal(m.headcount, 3);
  assert.equal(m.attendanceRate, 0.7057);
  assert.equal(m.isProvisional, true);
  assert.equal(m.provisionalDays, 2);
  assert.equal(m.noDataDays, 5);
  assert.equal(m.onLeaveDays, 3);
  assert.equal(m.missingCheckouts, 2);
  assert.equal(m.neverPunchedCount, 1);
  assert.equal(m.avgHours, 6.4);
});

test('adaptMetrics: null when no payload', () => {
  assert.equal(adaptMetrics(null), null);
});

test('adaptMetrics: daily fraction becomes a chart percentage + expected sum', () => {
  const [d0, d1, d2] = adaptMetrics(API).daily;
  assert.equal(d0.rate, 50);
  assert.equal(d0.expected, 4);
  assert.equal(d0.leave, 1);
  assert.equal(d1.rate, 25);
  assert.equal(d1.state, 'provisional');
  assert.equal(d1.expected, 4);
  assert.equal(d2.rate, null);
  assert.equal(d2.state, 'no_data');
});

test('adaptMetrics: employees map on_leave->leave and pass counts', () => {
  const e = adaptMetrics(API).employees[0];
  assert.equal(e.leave, 0);
  assert.equal(e.noRecord, 1);
  assert.equal(e.absent, 1);
  assert.equal(e.unverifiedCount, 0);
  assert.equal(e.neverPunched, false);
  assert.equal(e.team, 'Ops');
});

test('adaptMetrics: teams keep API rate (no recompute) and derive expected', () => {
  const t = adaptMetrics(API).teams[0];
  assert.equal(t.rate, 0.7057);
  assert.equal(t.expected, 18);
  assert.equal(t.noRecord, 5);
  assert.equal(t.isProvisional, true);
});
