"""Pure attendance status + rate logic (spec §2.1/§2.2). No DB, no I/O.

Definitions (implemented exactly, in order, first match wins):

1. date is weekend or public holiday            -> non_working (excluded)
2. working day AND org-wide zero punches        -> no_data (excluded)
3. employee has at least one punch              -> present
4. employee has leave covering the date         -> on_leave
5. date is on or before leave_coverage_through  -> absent
6. otherwise                                    -> unverified

Rates are sums, never an average of daily percentages:

    attendance_rate = present / (expected - on_leave)

where expected = employee-dates with status in {present, on_leave, absent,
unverified}. `no_data` and `non_working` never enter expected.
"""
from __future__ import annotations

from datetime import date, timedelta

STATUS_NON_WORKING = "non_working"
STATUS_NO_DATA = "no_data"
STATUS_PRESENT = "present"
STATUS_ON_LEAVE = "on_leave"
STATUS_ABSENT = "absent"
STATUS_UNVERIFIED = "unverified"
STATUS_PENDING = "pending"

COUNTED_STATUSES = {
    STATUS_PRESENT, STATUS_ON_LEAVE, STATUS_ABSENT, STATUS_UNVERIFIED,
}


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def is_weekend(d: date) -> bool:
    return d.weekday() >= 5  # Mon=0 .. Sat=5, Sun=6


def has_punch(rec: dict | None) -> bool:
    """Biometric punch = a check-in, a check-out, or an explicit present flag
    (mirrors the frontend's long-standing `hasPunch`)."""
    if not rec:
        return False
    return (rec.get("check_in") is not None
            or rec.get("check_out") is not None
            or bool(rec.get("present")))


def punch_count(rec: dict | None) -> int:
    if not rec:
        return 0
    return (1 if rec.get("check_in") is not None else 0) + \
           (1 if rec.get("check_out") is not None else 0)


def classify(*, d: date, rec: dict | None, on_leave: bool, holiday: bool,
             no_data: bool, coverage_through: date | None, today: date) -> dict:
    """Return {"status": ..., "flags": {...}} for one employee-date."""
    if is_weekend(d) or holiday:
        return {"status": STATUS_NON_WORKING, "flags": {}}
    if d > today:
        return {"status": STATUS_PENDING, "flags": {}}
    if no_data:
        return {"status": STATUS_NO_DATA, "flags": {}}

    punched = has_punch(rec)
    if punched:
        n = punch_count(rec)
        flags = {
            "missing_checkout": n == 1 and d < today,
            "in_progress": n <= 1 and d == today,
            "leave_conflict": bool(on_leave),
        }
        return {"status": STATUS_PRESENT, "flags": flags}
    if d == today:
        # Today is not finished: no punch yet is not absence.
        return {"status": STATUS_PENDING, "flags": {}}
    if on_leave:
        return {"status": STATUS_ON_LEAVE, "flags": {}}
    if coverage_through is not None and d <= coverage_through:
        return {"status": STATUS_ABSENT, "flags": {}}
    return {"status": STATUS_UNVERIFIED, "flags": {}}


def _rate(present: float, expected: float, on_leave: float):
    denom = expected - on_leave
    if denom <= 0:
        return None
    return present / denom


def _day_state(d: date, *, in_period_data: bool, coverage_through,
               today: date) -> str:
    if not in_period_data and d < today:
        return "no_data"
    if coverage_through is None or d > coverage_through:
        return "provisional"
    return "covered"


def build_metrics(*, employees: list[dict], records: dict, calendar: dict,
                  leave_dates: set, holidays: set, coverage_through,
                  start: date, end: date, today: date,
                  team_filter: set | None = None,
                  shift_filter: str | None = None,
                  exclude_never_punched: bool = False) -> dict:
    """Compute summary + daily series + team rows + per-employee detail.

    employees : [{id, name, team, shift}]
    records   : {(employee_id, date): {check_in, check_out, present, ...}}
    calendar  : {(employee_id, date): {kind, fraction, zoho_presence,
                                       leave_type}}
    leave_dates: {(employee_id, date)} approved legacy leave rows
    holidays  : {date}
    """
    dates = list(daterange(start, end))
    org_punch_dates = {d for (_eid, d), r in records.items() if has_punch(r)}

    roster = []
    for e in employees:
        if team_filter is not None and (e.get("team") or "Unassigned") not in team_filter:
            continue
        if shift_filter and (e.get("shift") or "").lower() != shift_filter:
            continue
        roster.append(e)

    leave_dates = leave_dates or set()
    holidays = holidays or set()

    emp_out = []
    for e in roster:
        eid = e["id"]
        counters = {
            "present": 0, "expected": 0, "on_leave": 0, "absent": 0,
            "unverified": 0, "leave_conflict": 0, "missing": 0,
            "hours_sum": 0.0, "hours_days": 0, "overtime": 0.0,
            "late": 0, "early": 0, "biometric": 0,
        }
        ever_punched = False
        days = []
        for d in dates:
            rec = records.get((eid, d))
            cal = calendar.get((eid, d))
            on_leave = bool(
                (cal and cal.get("kind") == "leave")
                or ((eid, d) in leave_dates)
            )
            no_data = d not in org_punch_dates
            result = classify(
                d=d, rec=rec, on_leave=on_leave,
                holiday=d in holidays, no_data=no_data,
                coverage_through=coverage_through, today=today)
            status = result["status"]
            flags = result["flags"]
            counted = status in COUNTED_STATUSES and d < today

            if has_punch(rec) and not is_weekend(d) and d not in holidays:
                ever_punched = ever_punched or d <= today
            if counted:
                counters["expected"] += 1
                counters[status] += 1
            if status == STATUS_PRESENT and d <= today:
                if flags.get("leave_conflict"):
                    counters["leave_conflict"] += 1
                if flags.get("missing_checkout"):
                    counters["missing"] += 1
                if punch_count(rec) >= 2:
                    h = float(rec.get("work_hours") or 0)
                    if h > 0:
                        counters["hours_sum"] += h
                        counters["hours_days"] += 1
                if (rec or {}).get("source") == "biometric":
                    counters["biometric"] += 1
                counters["overtime"] += float((rec or {}).get("overtime_hours") or 0)
                if (rec or {}).get("late_in"):
                    counters["late"] += 1
                if (rec or {}).get("early_out"):
                    counters["early"] += 1

            if status == STATUS_NON_WORKING:
                state = "non_working"
            elif status == STATUS_PENDING:
                state = "pending"
            else:
                state = _day_state(d, in_period_data=(d in org_punch_dates),
                                   coverage_through=coverage_through, today=today)
            days.append({
                "date": d.isoformat(),
                "status": status,
                "state": state,
                "leave_conflict": bool(flags.get("leave_conflict")),
                "missing_checkout": bool(flags.get("missing_checkout")),
                "in_progress": bool(flags.get("in_progress")),
                "check_in": _hhmm((rec or {}).get("check_in")),
                "check_out": _hhmm((rec or {}).get("check_out")),
                "hours": float((rec or {}).get("work_hours") or 0),
                "overtime": float((rec or {}).get("overtime_hours") or 0),
                "leave_type": (cal or {}).get("leave_type") if on_leave else None,
                "leave_fraction": float((cal or {}).get("fraction") or 1),
                "zoho_presence": (cal or {}).get("zoho_presence"),
                "source": (rec or {}).get("source"),
            })
        expected = counters["expected"]
        present = counters["present"]
        on_leave = counters["on_leave"]
        emp_out.append({
            "id": eid,
            "name": e.get("name"),
            "team": e.get("team") or "Unassigned",
            "shift": e.get("shift"),
            "present": present,
            "expected": expected,
            "on_leave": on_leave,
            "absent": counters["absent"],
            "unverified": counters["unverified"],
            "no_record": counters["absent"] + counters["unverified"],
            "missing": counters["missing"],
            "leave_conflict": counters["leave_conflict"],
            "never_punched": not ever_punched,
            "attendance_rate": _rate(present, expected, on_leave),
            "avg_hours": (round(counters["hours_sum"] / counters["hours_days"], 1)
                          if counters["hours_days"] else None),
            "hours": round(counters["hours_sum"], 1),
            "overtime": round(counters["overtime"], 1),
            "late": int(counters["late"]),
            "early": int(counters["early"]),
            "biometric_days": counters["biometric"],
            "days": days,
        })

    if exclude_never_punched:
        emp_out = [e for e in emp_out if not e["never_punched"]]

    headcount = len(emp_out)
    present_days = sum(e["present"] for e in emp_out)
    expected_days = sum(e["expected"] for e in emp_out)
    on_leave_days = sum(e["on_leave"] for e in emp_out)
    absent_days = sum(e["absent"] for e in emp_out)
    unverified_days = sum(e["unverified"] for e in emp_out)
    leave_conflict_days = sum(e["leave_conflict"] for e in emp_out)
    missing_checkouts = sum(e["missing"] for e in emp_out)
    no_punch_in_period = sum(1 for e in emp_out if e["never_punched"])
    hours_sum = sum(e["hours"] for e in emp_out)
    hours_days = sum(1 for e in emp_out for dd in e["days"]
                     if dd["status"] == STATUS_PRESENT
                     and dd["date"] < today.isoformat()
                     and dd["check_in"] and dd["check_out"])
    biometric_days = sum(e["biometric_days"] for e in emp_out)

    working_dates = [d for d in dates
                     if not is_weekend(d) and d not in holidays and d <= today]
    provisional_days = 0
    no_data_days = 0
    for d in working_dates:
        if d not in org_punch_dates:
            if d < today:
                no_data_days += 1
            continue
        if coverage_through is None or d > coverage_through:
            provisional_days += 1

    summary = {
        "headcount": headcount,
        "attendance_rate": _rate(present_days, expected_days, on_leave_days),
        "is_provisional": provisional_days > 0,
        "provisional_days": provisional_days,
        "no_data_days": no_data_days,
        "present_days": present_days,
        "on_leave_days": on_leave_days,
        "absent_days": absent_days,
        "unverified_days": unverified_days,
        "leave_conflict_days": leave_conflict_days,
        "missing_checkouts": missing_checkouts,
        "no_punch_in_period": no_punch_in_period,
        "avg_hours": round(hours_sum / hours_days, 1) if hours_days else None,
        "biometric_days": biometric_days,
    }

    daily = []
    for d in working_dates:
        counts = {STATUS_PRESENT: 0, STATUS_ON_LEAVE: 0,
                  STATUS_ABSENT: 0, STATUS_UNVERIFIED: 0}
        for e in emp_out:
            day = e["days"][dates.index(d)]
            if day["status"] in counts:
                counts[day["status"]] += 1
        expected = sum(counts.values())
        on_leave = counts[STATUS_ON_LEAVE]
        daily.append({
            "date": d.isoformat(),
            "status_counts": {
                "present": counts[STATUS_PRESENT],
                "on_leave": counts[STATUS_ON_LEAVE],
                "absent": counts[STATUS_ABSENT],
                "unverified": counts[STATUS_UNVERIFIED],
            },
            "attendance_rate": _rate(counts[STATUS_PRESENT], expected, on_leave),
            "state": _day_state(d, in_period_data=(d in org_punch_dates),
                                coverage_through=coverage_through, today=today),
        })

    teams = []
    team_names = sorted({e["team"] for e in emp_out})
    for name in team_names:
        members = [e for e in emp_out if e["team"] == name]
        t_present = sum(e["present"] for e in members)
        t_expected = sum(e["expected"] for e in members)
        t_leave = sum(e["on_leave"] for e in members)
        t_absent = sum(e["absent"] for e in members)
        t_unverified = sum(e["unverified"] for e in members)
        t_daily = []
        for d in working_dates:
            sc = {STATUS_PRESENT: 0, STATUS_ON_LEAVE: 0,
                  STATUS_ABSENT: 0, STATUS_UNVERIFIED: 0}
            for e in members:
                day = e["days"][dates.index(d)]
                if day["status"] in sc:
                    sc[day["status"]] += 1
            exp = sum(sc.values())
            t_daily.append({
                "date": d.isoformat(),
                "attendance_rate": _rate(sc[STATUS_PRESENT], exp,
                                         sc[STATUS_ON_LEAVE]),
            })
        t_prov = sum(1 for dd in t_daily
                     if dd["attendance_rate"] is not None
                     and (coverage_through is None
                          or date.fromisoformat(dd["date"]) > coverage_through))
        teams.append({
            "team": name,
            "headcount": len(members),
            "attendance_rate": _rate(t_present, t_expected, t_leave),
            "is_provisional": t_prov > 0,
            "provisional_days": t_prov,
            "no_data_days": no_data_days,
            "present_days": t_present,
            "on_leave_days": t_leave,
            "absent_days": t_absent,
            "unverified_days": t_unverified,
            "avg_hours": _avg_hours(members),
            "missing_checkouts": sum(e["missing"] for e in members),
            "no_punch_in_period": sum(1 for e in members if e["never_punched"]),
            "small": len(members) < 5,
            "daily": t_daily,
        })

    return {
        "summary": summary,
        "daily": daily,
        "teams": teams,
        "employees": emp_out,
        "coverage_through": coverage_through.isoformat() if coverage_through else None,
        "today": today.isoformat(),
    }


def _avg_hours(members: list[dict]):
    vals = [e["avg_hours"] for e in members if e["avg_hours"] is not None]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 1)


def _hhmm(t):
    if t is None:
        return None
    return t.strftime("%H:%M") if hasattr(t, "strftime") else str(t)[:5]


# --- roster (spec §7) -------------------------------------------------------

def build_roster(*, employees: list[dict], records: dict, calendar: dict,
                 leave_dates: set, holidays: set, coverage_through,
                 d: date, today: date, team_filter: set | None = None,
                 statuses: set | None = None) -> dict:
    """Return {date_state, rows} for one date, sorted by team then name."""
    org_punch_dates = {dd for (_eid, dd), r in records.items() if has_punch(r)}
    holiday = d in holidays
    is_non_working = is_weekend(d) or holiday
    no_data = (not is_non_working) and d not in org_punch_dates
    if is_non_working:
        date_state = "non_working"
    elif no_data:
        date_state = "no_data"
    elif coverage_through is None or d > coverage_through:
        date_state = "provisional"
    else:
        date_state = "covered"

    # Spec §7: no_data and non-working dates return an empty list + a
    # date_state the frontend turns into an explanatory message.
    if date_state in ("no_data", "non_working"):
        return {"date": d.isoformat(), "date_state": date_state, "rows": []}

    rows = []
    for e in employees:
        if team_filter is not None and (e.get("team") or "Unassigned") not in team_filter:
            continue
        eid = e["id"]
        rec = records.get((eid, d))
        cal = calendar.get((eid, d))
        on_leave = bool((cal and cal.get("kind") == "leave")
                        or ((eid, d) in (leave_dates or set())))
        result = classify(d=d, rec=rec, on_leave=on_leave, holiday=holiday,
                          no_data=no_data, coverage_through=coverage_through,
                          today=today)
        status = result["status"]
        if statuses and status not in statuses:
            continue
        first = last = None
        if status == STATUS_PRESENT:
            ci, co = (rec or {}).get("check_in"), (rec or {}).get("check_out")
            # Night shifts cross midnight: order by wall-clock start/end.
            if ci is not None and co is not None and co < ci:
                first, last = ci, co
            else:
                first, last = ci, co
        rows.append({
            "employee_id": eid,
            "name": e.get("name"),
            "team": e.get("team") or "Unassigned",
            "status": status,
            "first_punch": _hhmm(first),
            "last_punch": _hhmm(last),
            "hours_worked": float((rec or {}).get("work_hours") or 0),
            "missing_checkout": bool(result["flags"].get("missing_checkout")),
            "leave_conflict": bool(result["flags"].get("leave_conflict")),
        })
    rows.sort(key=lambda r: ((r["team"] or ""), (r["name"] or "")))
    return {"date": d.isoformat(), "date_state": date_state, "rows": rows}


ROSTER_COLUMNS = ["employee_id", "name", "team", "status", "first_punch",
                  "last_punch", "hours_worked", "missing_checkout"]


def _csv_safe(value) -> str:
    s = "" if value is None else str(value)
    if s[:1] in ("=", "+", "-", "@"):
        s = "'" + s
    return s


def roster_csv(roster: dict) -> str:
    import csv as _csv
    import io

    buf = io.StringIO()
    writer = _csv.writer(buf, lineterminator="\r\n")
    writer.writerow(ROSTER_COLUMNS)
    for r in roster["rows"]:
        writer.writerow([_csv_safe(r.get(c)) for c in ROSTER_COLUMNS])
    return buf.getvalue()


def team_slug(name: str) -> str:
    import re
    s = re.sub(r"[^a-z0-9]+", "-", (name or "unassigned").lower())
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "unassigned"
