// Regression test: /leave/calendar returns a {total, days} envelope and
// fetchDayRecords must page through it (a bare-array assumption silently
// dropped the whole overlay and every leave day read as absent_unverified).
import { test, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';

const realFetch = globalThis.fetch;
let routes = {};
let failCalendar = false;

function json(body) {
  return { ok: true, json: async () => body, text: async () => JSON.stringify(body) };
}

beforeEach(() => {
  routes = {};
  failCalendar = false;
  globalThis.fetch = async (url) => {
    const u = String(url);
    if (u.includes('/leave/calendar')) {
      if (failCalendar) return { ok: false, status: 500, text: async () => 'boom' };
      const q = new URL(u, 'http://x');
      const limit = Number(q.searchParams.get('limit') || 5000);
      const offset = Number(q.searchParams.get('offset') || 0);
      const all = routes.calendar || [];
      return json({ total: all.length, limit, offset, days: all.slice(offset, offset + limit) });
    }
    if (u.includes('/attendance')) return json(routes.attendance || []);
    if (u.includes('/wfh')) return json([]);
    if (u.includes('/leave')) return json([]);
    if (u.includes('/holidays')) return json([]);
    throw new Error(`unexpected fetch ${u}`);
  };
});

afterEach(() => { globalThis.fetch = realFetch; });

function calRow(emp, date, kind, raw) {
  return {
    employee_id: emp, date, source: 'xls', raw_code: raw, day_kind: kind,
    leave_code: kind === 'leave' ? raw : null, leave_fraction: 1.0,
    zoho_presence: raw === 'P', leave_type: kind === 'leave' ? 'Annual Leave' : null,
  };
}

function attRow(emp, date) {
  return {
    employee_id: emp, employee_name: `Emp ${emp}`, date,
    check_in: null, check_out: null, work_hours: 0, overtime_hours: 0,
    late_in: false, early_out: false, present: false, team_name: 'Test',
    assigned_shift: null, matched_shift: null, shift_anomaly: false, source: 'migrated',
  };
}

test('calendar envelope pages are all merged into day records', async () => {
  const { fetchDayRecords } = await import('../src/api.js');
  const days = [];
  for (let i = 0; i < 5002; i++) {
    const d = `2026-08-${String((i % 28) + 1).padStart(2, '0')}`;
    days.push(calRow(`e${i % 50}`, d, 'working', 'P'));
  }
  days.push(calRow('13451', '2026-08-03', 'leave', 'SL'));
  days.push(calRow('13451', '2026-08-04', 'leave', 'SL'));
  routes.calendar = days;
  routes.attendance = [attRow('13451', '2026-08-03'), attRow('13451', '2026-08-04')];
  const { records, calMeta, calendarOk } = await fetchDayRecords({});
  assert.equal(calendarOk, true);
  assert.equal(Object.keys(calMeta).length, 51);
  const got = records.filter((r) => r.employeeId === '13451').sort((a, b) => a.date.localeCompare(b.date));
  assert.equal(got.length, 2);
  assert.equal(got[0].dayKind, 'leave');
  assert.equal(got[0].rawCode, 'SL');
  assert.equal(got[1].dayKind, 'leave');
});

test('calendar failure degrades loudly instead of silently', async () => {
  const { fetchDayRecords } = await import('../src/api.js');
  failCalendar = true;
  routes.attendance = [attRow('1', '2026-08-03')];
  const { records, calendarOk } = await fetchDayRecords({});
  assert.equal(calendarOk, false);
  assert.equal(records.length, 1);
  assert.equal(records[0].dayKind, undefined);
});
