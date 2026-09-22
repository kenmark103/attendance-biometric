// API adapter — turns normalized /attendance + /leave into the flat RAW shape
// the dashboard expects: [id,name,date,in, out, hours, overtime, late, early, present, team, leave, hasLeaveData, exemption]
const API_BASE = import.meta.env.VITE_API_URL || '/api';

function apiUrl(path) {
  // in dev VITE_API_URL is empty -> use /api proxy; in prod set to http://localhost:8001
  if (API_BASE === '/api') return `/api${path}`;
  return `${API_BASE.replace(/\/$/, '')}${path}`;
}

export async function fetchTeams() {
  const r = await fetch(apiUrl('/teams'));
  if (!r.ok) throw new Error(`teams ${r.status}`);
  return r.json();
}

export async function fetchAttendance({ date_from, date_to, team_id } = {}) {
  const p = new URLSearchParams();
  if (date_from) p.set('date_from', date_from);
  if (date_to) p.set('date_to', date_to);
  if (team_id) p.set('team_id', team_id);
  const qs = p.toString() ? `?${p}` : '';
  const r = await fetch(apiUrl(`/attendance${qs}`));
  if (!r.ok) throw new Error(`attendance ${r.status}`);
  return r.json();
}

export async function fetchLeave({ date_from, date_to, employee_id } = {}) {
  const p = new URLSearchParams();
  if (date_from) p.set('date_from', date_from);
  if (date_to) p.set('date_to', date_to);
  if (employee_id) p.set('employee_id', employee_id);
  const qs = p.toString() ? `?${p}` : '';
  const r = await fetch(apiUrl(`/leave${qs}`));
  if (!r.ok) throw new Error(`leave ${r.status}`);
  return r.json();
}

// Build RAW rows from attendance + leave, mirroring scripts/load_data.py join.
// We fetch attendance and leave separately then merge by (employee_id, date).
export async function fetchRaw({ date_from, date_to } = {}) {
  const [attendance, leave] = await Promise.all([
    fetchAttendance({ date_from, date_to }),
    fetchLeave({ date_from, date_to }),
  ]);

  // index leave by employee_id|date -> leave_type (first one). If multiple leave types same day, join with ", "
  const leaveByKey = new Map();
  const exemptByKey = new Map();
  for (const l of leave) {
    const k = `${l.employee_id}|${l.date.slice(0, 10)}`;
    // l.date may be "2026-08-03" or ISO; normalize
    const d = l.date.slice(0, 10);
    const k2 = `${l.employee_id}|${d}`;
    const cur = leaveByKey.get(k2);
    if (!cur) leaveByKey.set(k2, l.leave_type);
    else leaveByKey.set(k2, `${cur}, ${l.leave_type}`);
    // exemption = Maternity/whatever that shows as exempt in original dashboard
    // Original: exemptionReason field was used for Maternity Leave etc when present==0
    // We treat leave_type containing Maternity/WFH/Exempt as exemption as well
    if (/maternity|wfh|exempt|onsite/i.test(l.leave_type)) {
      const curE = exemptByKey.get(k2);
      if (!curE) exemptByKey.set(k2, l.leave_type);
    }
  }

  // hasLeaveData: in original data, hasLeaveData was 1 when Zoho leave data existed for that employee.
  // Now we approximate: 1 if we have any leave row for that employee at all, else 1 (since system has leave data).
  // For employees with no leave rows ever, we still assume hasLeaveData=true (API is authoritative).
  // This keeps "unverified" only for dates we intentionally lack leave coverage — which shouldn't happen now.
  const employeesWithLeave = new Set(leave.map((l) => l.employee_id));

  const raw = attendance.map((a) => {
    const d = a.date.slice(0, 10);
    const k = `${a.employee_id}|${d}`;
    const leaveType = leaveByKey.get(k) || '';
    const exemption = exemptByKey.get(k) || '';
    // If present==false and exemption present, dashboard shows exempt status
    // If present==false and leaveType present, shows approved
    const hasLeaveData = 1;
    return [
      a.employee_id,
      a.employee_name,
      d,
      a.check_in ? a.check_in.slice(0, 5) : null,
      a.check_out ? a.check_out.slice(0, 5) : null,
      Number(a.work_hours ?? 0),
      Number(a.overtime_hours ?? 0),
      a.late_in ? 1 : 0,
      a.early_out ? 1 : 0,
      a.present ? 1 : 0,
      a.team_name || 'Unassigned',
      leaveType,
      hasLeaveData,
      exemption,
    ];
  });

  // The attendance table only has rows for days where an employee existed (4356 rows).
  // The original dashboard computed missing days as unverified — we keep that behavior
  // by leaving gaps as-is; the dashboard's computeDerived will treat absent dates accordingly
  // because weekdayRecordsAll only contains existing rows, and DayChips falls back to unverified.

  // Sort by date then name for stable rendering
  raw.sort((x, y) => (x[2] === y[2] ? x[1].localeCompare(y[1]) : x[2].localeCompare(y[2])));
  return raw;
}
