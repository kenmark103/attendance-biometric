// API layer — same-origin (nginx /api/ prefix in prod, vite proxy in dev),
// refresh cookie sent automatically. Access token in memory via auth.js.
import { apiFetch } from './auth.js';

const API_BASE = (import.meta.env.VITE_API_URL || '/api').replace(/\/$/, '');

function apiUrl(path) {
  return `${API_BASE}${path}`;
}

async function getJSON(path, params = {}) {
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') p.set(k, v);
  });
  const qs = p.toString() ? `?${p}` : '';
  const r = await apiFetch(apiUrl(`${path}${qs}`));
  if (!r.ok) throw new Error(`${path} ${r.status}`);
  return r.json();
}

async function postJSON(path, body) {
  const r = await apiFetch(apiUrl(path), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(`${path} ${r.status}: ${await r.text()}`);
  return r.json();
}

async function patchJSON(path, body) {
  const r = await apiFetch(apiUrl(path), { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(`${path} ${r.status}: ${await r.text()}`);
  return r.json();
}

async function delJSON(path) {
  const r = await apiFetch(apiUrl(path), { method: 'DELETE' });
  if (!r.ok) throw new Error(`${path} ${r.status}: ${await r.text()}`);
  return r.json();
}

export const fetchTeams = () => getJSON('/teams');
export const fetchAttendance = (params) => getJSON('/attendance', params);
export const fetchLeave = (params) => getJSON('/leave', params);
export const fetchHolidays = (params) => getJSON('/holidays', params);
export const fetchWfh = (params) => getJSON('/wfh', params);
export const fetchEmployees = () => getJSON('/employees');
export const fetchCoverage = () => getJSON('/stats/coverage');
export const fetchSyncLog = (limit = 50) => getJSON('/sync-log', { limit });
export const createWfh = (payload) => postJSON('/wfh', payload);
export const deleteWfh = (id) => delJSON(`/wfh/${id}`);

// --- auth / admin ---
export const changePassword = (current_password, new_password) =>
  postJSON('/auth/change-password', { current_password, new_password });
export const fetchUsers = () => getJSON('/users');
export const createUser = (payload) => postJSON('/users', payload);
export const patchUser = (id, payload) => patchJSON(`/users/${id}`, payload);
export const resetUserPassword = (id) => postJSON(`/users/${id}/reset-password`, {});
export const fetchAuthEvents = (limit = 100) => getJSON('/auth/events', { limit });

function toDateStr(d) {
  return d ? String(d).slice(0, 10) : d;
}
function toTimeStr(t) {
  return t ? String(t).slice(0, 5) : null;
}

/**
 * One record per (employee, date) that actually exists in attendance_records.
 *
 * Paginates through /attendance (and /leave, /wfh) so a dataset larger
 * than one page is never silently truncated — the old single-request
 * shape dropped everything past the API's row limit.
 *
 * Known limitation, worth knowing about rather than silently working around:
 * this only covers dates that HAVE a row. If a sync ever fails to write a
 * day at all (not present=false, but no row whatsoever — the "partial sync"
 * failure mode from the design discussion), that gap is invisible here.
 * The Sync-check tab + /stats/coverage exists precisely to surface that:
 * compare per-date counts against the source file instead of trusting
 * this list's length.
 */
const PAGE_SIZE = 5000;

async function fetchAllPaged(fetchFn, params = {}) {
  const out = [];
  let offset = 0;
  for (;;) {
    const page = await fetchFn({ ...params, limit: PAGE_SIZE, offset });
    out.push(...page);
    if (page.length < PAGE_SIZE) break;
    offset += PAGE_SIZE;
  }
  return out;
}

export async function fetchDayRecords({ date_from, date_to, team_id } = {}) {
  const [attendance, leave, holidays, wfh] = await Promise.all([
    fetchAllPaged(fetchAttendance, { date_from, date_to, team_id }),
    fetchAllPaged(fetchLeave, { date_from, date_to }),
    fetchHolidays({ date_from, date_to }),
    fetchAllPaged(fetchWfh, { date_from, date_to }).catch(() => []),
  ]);

  const holidayByDate = new Map(holidays.map((h) => [toDateStr(h.date), h.name]));
  const wfhByKey = new Set(wfh.map((w) => `${w.employee_id}|${toDateStr(w.date)}`));

  const leavesByKey = new Map(); // "employeeId|date" -> [{type, status}]
  for (const l of leave) {
    const key = `${l.employee_id}|${toDateStr(l.date)}`;
    const list = leavesByKey.get(key) || [];
    list.push({ type: l.leave_type, status: l.status });
    leavesByKey.set(key, list);
  }

  const records = attendance.map((a) => {
    const date = toDateStr(a.date);
    const key = `${a.employee_id}|${date}`;
    const holidayName = holidayByDate.get(date) || null;

    const isWfh = wfhByKey.has(key);
    return {
      employeeId: a.employee_id,
      name: a.employee_name,
      team: a.team_name || 'Unassigned',
      date,
      checkIn: toTimeStr(a.check_in),
      checkOut: toTimeStr(a.check_out),
      hours: Number(a.work_hours ?? 0),
      overtime: Number(a.overtime_hours ?? 0),
      late: !!a.late_in,
      early: !!a.early_out,
      present: !!a.present || isWfh,
      wfh: isWfh,
      source: isWfh ? 'wfh' : (a.source || 'migrated'),
      assignedShift: a.assigned_shift || null,
      matchedShift: a.matched_shift || null,
      shiftAnomaly: !!a.shift_anomaly,
      leaves: leavesByKey.get(key) || [],
      isHoliday: !!holidayName,
      holidayName,
    };
  });

  records.sort((x, y) => (x.date === y.date ? x.name.localeCompare(y.name) : x.date.localeCompare(y.date)));
  return records;
}
