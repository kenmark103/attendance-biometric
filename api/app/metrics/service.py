"""DB loaders for the metrics module. Keeps SQL in one place; `core` stays
pure. Uses the same source-priority rule as GET /leave/calendar.
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.core import settings

NAIROBI = ZoneInfo("Africa/Nairobi")


def today_local() -> date:
    return datetime.now(NAIROBI).date()


def _priority_case(alias: str = "c") -> str:
    priority = [s for s in settings.LEAVE_SOURCE_PRIORITY if s in ("api", "xls")]
    for s in ("api", "xls"):
        if s not in priority:
            priority.append(s)
    return " ".join(f"WHEN '{s}' THEN {i}" for i, s in enumerate(priority))


def load_employees(conn, *, active_only: bool = True) -> list[dict]:
    """Employee roster with the team shown on the dashboard (latest
    attendance team, falling back to the current snapshot)."""
    clause = "WHERE e.status = 'active'" if active_only else ""
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT e.id, e.name, e."current_shift" AS shift,
               COALESCE(lt.name, ct.name, 'Unassigned') AS team
        FROM employees e
        LEFT JOIN teams ct ON ct.id = e.current_team_id
        LEFT JOIN LATERAL (
            SELECT t.name
            FROM attendance_records a JOIN teams t ON t.id = a.team_id
            WHERE a.employee_id = e.id AND a.team_id IS NOT NULL
            ORDER BY a.date DESC LIMIT 1
        ) lt ON TRUE
        {clause}
        ORDER BY e.name
        """)
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    return rows


def load_records(conn, start: date, end: date) -> dict:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT employee_id, date, check_in, check_out, work_hours,
               overtime_hours, late_in, early_out, present, assigned_shift,
               matched_shift, shift_anomaly, source
        FROM attendance_records
        WHERE date BETWEEN %s AND %s
        """, (start, end))
    out = {}
    for r in cur.fetchall():
        out[(r["employee_id"], r["date"])] = dict(r)
    cur.close()
    return out


def load_calendar(conn, start: date, end: date, *, privileged: bool) -> dict:
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT d.employee_id, d.date, d.kind, d.fraction, d.zoho_presence,
               d.leave_code, m.label
        FROM (
            SELECT DISTINCT ON (c.employee_id, c.date)
                c.employee_id, c.date, c.kind, c.fraction, c.zoho_presence,
                c.leave_code
            FROM calendar_day c
            WHERE c.date BETWEEN %s AND %s
            ORDER BY c.employee_id, c.date,
                     CASE c.source {_priority_case()} ELSE 99 END
        ) d LEFT JOIN leave_code_map m ON m.code = d.leave_code
        """, (start, end))
    out = {}
    for r in cur.fetchall():
        kind = r["kind"]
        if kind != "leave":
            leave_type = None
        elif privileged:
            leave_type = r["label"] or r["leave_code"] or "On leave"
        else:
            leave_type = "On leave"
        out[(r["employee_id"], r["date"])] = {
            "kind": kind,
            "fraction": float(r["fraction"]),
            "zoho_presence": r["zoho_presence"],
            "leave_type": leave_type,
        }
    cur.close()
    return out


def load_leave_dates(conn, start: date, end: date) -> set:
    cur = conn.cursor()
    cur.execute(
        "SELECT employee_id, date FROM leave_records "
        "WHERE date BETWEEN %s AND %s AND status = 'approved'",
        (start, end))
    out = {(r["employee_id"], r["date"]) for r in cur.fetchall()}
    cur.close()
    return out


def load_holidays(conn, start: date, end: date) -> set:
    cur = conn.cursor()
    cur.execute("SELECT date FROM holidays WHERE date BETWEEN %s AND %s",
                (start, end))
    out = {r["date"] for r in cur.fetchall()}
    cur.close()
    return out


def load_coverage_through(conn):
    cur = conn.cursor()
    cur.execute("SELECT source, through_date FROM leave_coverage")
    rows = {r["source"]: r["through_date"] for r in cur.fetchall()}
    cur.close()
    return rows.get("xls") or rows.get("api")


def resolve_team_filter(conn, tokens) -> set | None:
    """Resolve comma-separated team slugs OR names to a set of names.
    Returns None when no filter is requested."""
    from app.metrics.core import team_slug

    wanted = [t.strip() for t in (tokens or []) if t and t.strip()]
    if not wanted:
        return None
    cur = conn.cursor()
    cur.execute("SELECT name FROM teams")
    names = [r["name"] for r in cur.fetchall()]
    cur.close()
    by_slug = {team_slug(n): n for n in names}
    by_lower = {n.lower(): n for n in names}
    resolved = set()
    for tok in wanted:
        if tok in by_slug:
            resolved.add(by_slug[tok])
        elif tok.lower() in by_lower:
            resolved.add(by_lower[tok.lower()])
    return resolved


def load_all(conn, start: date, end: date, *, privileged: bool) -> dict:
    return {
        "employees": load_employees(conn),
        "records": load_records(conn, start, end),
        "calendar": load_calendar(conn, start, end, privileged=privileged),
        "leave_dates": load_leave_dates(conn, start, end),
        "holidays": load_holidays(conn, start, end),
        "coverage_through": load_coverage_through(conn),
    }
