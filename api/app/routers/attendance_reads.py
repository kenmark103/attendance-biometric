"""Read-only attendance and coverage endpoints."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.core import settings
from app.core.db import get_db
from app.core.deps import viewer

router = APIRouter(tags=["attendance"])


@router.get("/teams")
def list_teams(user=Depends(viewer), conn=Depends(get_db)):
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM teams ORDER BY name")
    rows = cur.fetchall()
    cur.close()
    return rows


@router.get("/employees")
def list_employees(team_id: Optional[int] = None, user=Depends(viewer),
                   conn=Depends(get_db)):
    cur = conn.cursor()
    if team_id:
        cur.execute(
            "SELECT id, name, current_role, current_shift FROM employees WHERE current_team_id = %s ORDER BY name",
            (team_id,),
        )
    else:
        cur.execute("SELECT id, name, current_role, current_shift, status, current_team_id FROM employees ORDER BY name")
    rows = cur.fetchall()
    cur.close()
    return rows


@router.get("/attendance")
def get_attendance(
    employee_id: Optional[str] = None,
    team_id: Optional[int] = None,
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    limit: int = Query(5000, ge=1, le=20000),
    offset: int = Query(0, ge=0),
    user=Depends(viewer),
    conn=Depends(get_db),
):
    cur = conn.cursor()

    clauses, params = [], []
    if employee_id:
        clauses.append("a.employee_id = %s"); params.append(employee_id)
    if team_id:
        clauses.append("a.team_id = %s"); params.append(team_id)
    if date_from:
        clauses.append("a.date >= %s"); params.append(date_from)
    if date_to:
        clauses.append("a.date <= %s"); params.append(date_to)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    cur.execute(
        f"""
        SELECT
            a.id, a.employee_id, e.name AS employee_name, a.date,
            a.check_in, a.check_out, a.work_hours, a.overtime_hours,
            a.late_in, a.early_out, a.present,
            t.name AS team_name, a.assigned_shift, a.matched_shift,
            a.shift_anomaly, a.source
        FROM attendance_records a
        JOIN employees e ON e.id = a.employee_id
        LEFT JOIN teams t ON t.id = a.team_id
        {where}
        ORDER BY a.date DESC, e.name
        LIMIT %s OFFSET %s
        """,
        [*params, limit, offset],
    )
    rows = cur.fetchall()
    cur.close()
    return rows


@router.get("/leave")
def get_leave(
    employee_id: Optional[str] = None,
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    limit: int = Query(5000, ge=1, le=20000),
    offset: int = Query(0, ge=0),
    user=Depends(viewer),
    conn=Depends(get_db),
):
    cur = conn.cursor()

    clauses, params = [], []
    if employee_id:
        clauses.append("l.employee_id = %s"); params.append(employee_id)
    if date_from:
        clauses.append("l.date >= %s"); params.append(date_from)
    if date_to:
        clauses.append("l.date <= %s"); params.append(date_to)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    cur.execute(
        f"""
        SELECT l.id, l.employee_id, e.name AS employee_name, l.date,
               l.leave_type, l.status, l.source
        FROM leave_records l
        JOIN employees e ON e.id = l.employee_id
        {where}
        ORDER BY l.date DESC
        LIMIT %s OFFSET %s
        """,
        [*params, limit, offset],
    )
    rows = cur.fetchall()
    cur.close()
    return rows


@router.get("/holidays")
def get_holidays(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    user=Depends(viewer),
    conn=Depends(get_db),
):
    """Empty until the Zoho holiday sync exists — table is ready, nothing populates it yet."""
    cur = conn.cursor()
    clauses, params = [], []
    if date_from:
        clauses.append("date >= %s"); params.append(date_from)
    if date_to:
        clauses.append("date <= %s"); params.append(date_to)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cur.execute(f"SELECT id, date, name, source FROM holidays {where} ORDER BY date", params)
    rows = cur.fetchall()
    cur.close()
    return rows


@router.get("/stats/coverage")
def stats_coverage(user=Depends(viewer), conn=Depends(get_db)):
    """Sync-verification aggregate: proves what actually landed in the DB.

    Returns total attendance rows, date range, per-date counts, per-month
    counts, employee/team counts, leave + holiday totals, and the
    latest sync_log entries — everything the Sync-check tab needs to
    compare DB state against the source file, in one request.
    """
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) AS n, MIN(date) AS dmin, MAX(date) AS dmax FROM attendance_records"
    )
    totals = cur.fetchone()
    cur.execute(
        "SELECT date, COUNT(*) AS n FROM attendance_records GROUP BY date ORDER BY date"
    )
    per_date = cur.fetchall()
    cur.execute(
        "SELECT to_char(date, 'YYYY-MM') AS month, COUNT(*) AS n "
        "FROM attendance_records GROUP BY 1 ORDER BY 1"
    )
    per_month = cur.fetchall()
    cur.execute("SELECT COUNT(*) AS n FROM employees")
    n_employees = cur.fetchone()["n"]
    cur.execute("SELECT COUNT(*) AS n FROM teams")
    n_teams = cur.fetchone()["n"]
    cur.execute("SELECT COUNT(*) AS n FROM leave_records")
    n_leave = cur.fetchone()["n"]
    cur.execute("SELECT COUNT(*) AS n FROM holidays")
    n_holidays = cur.fetchone()["n"]
    cur.execute(
        "SELECT to_char(date, 'YYYY-MM') AS month FROM leave_records "
        "GROUP BY 1 HAVING COUNT(*) > 0 ORDER BY 1"
    )
    leave_by_month = [r["month"] for r in cur.fetchall()]
    cur.execute(
        "SELECT id, source, run_at, records_processed, records_failed, status, notes "
        "FROM sync_log ORDER BY id DESC LIMIT 20"
    )
    sync_log = cur.fetchall()
    cur.execute("SELECT service, state, since, last_error, updated_at FROM sync_state")
    sync_state = {
        r["service"]: {
            "state": r["state"],
            "since": str(r["since"]),
            "last_error": r["last_error"],
            "updated_at": str(r["updated_at"]),
        }
        for r in cur.fetchall()
    }
    cur.execute("SELECT source, through_date FROM leave_coverage")
    leave_coverage = {r["source"]: str(r["through_date"]) for r in cur.fetchall()}
    cur.close()
    return {
        "attendance_rows": totals["n"],
        "date_min": str(totals["dmin"]) if totals["dmin"] else None,
        "date_max": str(totals["dmax"]) if totals["dmax"] else None,
        "per_date": [{"date": str(r["date"]), "count": r["n"]} for r in per_date],
        "per_month": [{"month": r["month"], "count": r["n"]} for r in per_month],
        "employees": n_employees,
        "teams": n_teams,
        "leave_rows": n_leave,
        "leave_by_month": leave_by_month,
        "leave_coverage": {
            "through_date": leave_coverage.get("xls") or leave_coverage.get("api"),
            "source": "xls" if "xls" in leave_coverage
            else ("api" if leave_coverage else None),
        },
        "trust_zoho_presence": settings.TRUST_ZOHO_PRESENCE,
        "sync_state": sync_state,
        "holidays": n_holidays,
        "sync_log": [
            {
                "id": r["id"],
                "source": r["source"],
                "run_at": str(r["run_at"]),
                "records_processed": r["records_processed"],
                "records_failed": r["records_failed"],
                "status": r["status"],
                "notes": r["notes"],
            }
            for r in sync_log
        ],
    }


@router.get("/sync-log")
def list_sync_log(limit: int = Query(50, ge=1, le=200), user=Depends(viewer),
                  conn=Depends(get_db)):
    cur = conn.cursor()
    cur.execute(
        "SELECT id, source, run_at, records_processed, records_failed, status, notes "
        "FROM sync_log ORDER BY id DESC LIMIT %s",
        (limit,),
    )
    rows = cur.fetchall()
    cur.close()
    return rows



