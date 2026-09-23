// API layer — fetches attendance, leave, and holidays and merges them into
// rich per-day records. Deliberately does NOT flatten back into the old
// fixed-position tuple shape: source, shift_anomaly, and holiday data have
// nowhere to live in that shape, which is exactly what was being dropped.
const API_BASE = import.meta.env.VITE_API_URL || '/api';

function apiUrl(path) {
  if (API_BASE === '/api') return `/api${path}`;
  return `${API_BASE.replace(/\/$/, '')}${path}`;
}

async function getJSON(path, params = {}) {
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') p.set(k, v);
  });
  const qs = p.toString() ? `?${p}` : '';
  const r = await fetch(apiUrl(`${path}${qs}`));
  if (!r.ok) throw new Error(`${path} ${r.status}`);
  return r.json();
}

export const fetchTeams = () => getJSON('/teams');
export const fetchAttendance = (params) => getJSON('/attendance', params);
export const fetchLeave = (params) => getJSON('/leave', params);
export const fetchHolidays = (params) => getJSON('/holidays', params);

function toDateStr(d) {
  return d ? String(d).slice(0, 10) : d;
}
function toTimeStr(t) {
  return t ? String(t).slice(0, 5) : null;
}

/**
 * One record per (employee, date) that actually exists in attendance_records.
 *
 * Known limitation, worth knowing about rather than silently working around:
 * this only covers dates that HAVE a row. If a sync ever fails to write a
 * day at all (not present=false, but no row whatsoever — the "partial sync"
 * failure mode from the design discussion), that gap is invisible here.
 * Detecting it properly needs each employee's active date range, which the
 * schema doesn't cleanly expose yet (employees.status is active/offboarded,
 * not a date range) — flagging this as a real open item, not solving it
 * with a guess the way the old hasLeaveData hack did.
 */
export async function fetchDayRecords({ date_from, date_to, team_id } = {}) {
  const [attendance, leave, holidays] = await Promise.all([
    fetchAttendance({ date_from, date_to, team_id }),
    fetchLeave({ date_from, date_to }),
    fetchHolidays({ date_from, date_to }),
  ]);

  const holidayByDate = new Map(holidays.map((h) => [toDateStr(h.date), h.name]));

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
      present: !!a.present,
      source: a.source || 'migrated',       // 'biometric' | 'zoho_manual' | 'migrated'
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
