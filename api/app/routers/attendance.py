"""Attendance domain: teams, employees, records, leave, holidays,
coverage, sync log, and the bulk-ingestion choke points."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extras import execute_values

from app.core.db import get_conn
from app.core.deps import admin, viewer
from app.routers.schemas import (
    BulkAttendanceIn,
    BulkAttendanceTeamUpdateIn,
    BulkLeaveIn,
)

router = APIRouter(tags=["attendance"])


@router.get("/teams")
def list_teams(user=Depends(viewer)):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM teams ORDER BY name")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


@router.get("/employees")
def list_employees(team_id: Optional[int] = None, user=Depends(viewer)):
    conn = get_conn()
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
    conn.close()
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
):
    conn = get_conn()
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
    conn.close()
    return rows


@router.get("/leave")
def get_leave(
    employee_id: Optional[str] = None,
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    limit: int = Query(5000, ge=1, le=20000),
    offset: int = Query(0, ge=0),
    user=Depends(viewer),
):
    conn = get_conn()
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
    conn.close()
    return rows


@router.get("/holidays")
def get_holidays(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    user=Depends(viewer),
):
    """Empty until the Zoho holiday sync exists — table is ready, nothing populates it yet."""
    conn = get_conn()
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
    conn.close()
    return rows


@router.get("/stats/coverage")
def stats_coverage(user=Depends(viewer)):
    """Sync-verification aggregate: proves what actually landed in the DB.

    Returns total attendance rows, date range, per-date counts, per-month
    counts, employee/team counts, leave + holiday + wfh totals, and the
    latest sync_log entries — everything the Sync-check tab needs to
    compare DB state against the source file, in one request.
    """
    conn = get_conn()
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
    cur.execute("SELECT COUNT(*) AS n FROM wfh_approvals")
    n_wfh = cur.fetchone()["n"]
    cur.execute(
        "SELECT id, source, run_at, records_processed, records_failed, status, notes "
        "FROM sync_log ORDER BY id DESC LIMIT 20"
    )
    sync_log = cur.fetchall()
    cur.close()
    conn.close()
    return {
        "attendance_rows": totals["n"],
        "date_min": str(totals["dmin"]) if totals["dmin"] else None,
        "date_max": str(totals["dmax"]) if totals["dmax"] else None,
        "per_date": [{"date": str(r["date"]), "count": r["n"]} for r in per_date],
        "per_month": [{"month": r["month"], "count": r["n"]} for r in per_month],
        "employees": n_employees,
        "teams": n_teams,
        "leave_rows": n_leave,
        "holidays": n_holidays,
        "wfh_rows": n_wfh,
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
def list_sync_log(limit: int = Query(50, ge=1, le=200), user=Depends(viewer)):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, source, run_at, records_processed, records_failed, status, notes "
        "FROM sync_log ORDER BY id DESC LIMIT %s",
        (limit,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


# --- Bulk ingestion ------------------------------------------------------
# One choke point for writing attendance/leave data, used by:
#   - the JSON migration script (source='migrated')
#   - eventually, real biometric ingestion (source='biometric')
#   - eventually, Zoho manual-checkin sync (source='zoho_manual')
# `source` is a property of the WHOLE batch, set by which caller is
# calling — never a per-row field a caller could freely set. That's what
# keeps the trust-tier design meaningful.

ALLOWED_SOURCES = {"biometric", "zoho_manual", "migrated"}
INSERT_CHUNK_SIZE = 500  # matters at real biometric-feed volume, not at today's scale


@router.post("/attendance/bulk")
def bulk_insert_attendance(payload: BulkAttendanceIn, user=Depends(admin)):
    if payload.source not in ALLOWED_SOURCES:
        raise HTTPException(status_code=400, detail=f"source must be one of {sorted(ALLOWED_SOURCES)}")
    if not payload.records:
        return {"inserted": 0, "teams_created": 0, "employees_upserted": 0}

    conn = get_conn()
    cur = conn.cursor()

    # Teams and employees have to exist before attendance can reference
    # them (foreign keys) — same Zoho-first ordering discussed earlier,
    # just enforced here structurally rather than by convention.
    team_names = sorted({(r.team_name or "").strip() for r in payload.records if (r.team_name or "").strip()})
    execute_values(
        cur, "INSERT INTO teams (name) VALUES %s ON CONFLICT (name) DO NOTHING",
        [(t,) for t in team_names],
    )
    cur.execute("SELECT id, name FROM teams")
    team_id_by_name = {row["name"]: row["id"] for row in cur.fetchall()}

    employees = {(r.employee_id, r.employee_name) for r in payload.records}
    execute_values(
        cur,
        "INSERT INTO employees (id, name) VALUES %s ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name",
        list(employees),
    )

    inserted = 0
    for i in range(0, len(payload.records), INSERT_CHUNK_SIZE):
        chunk = payload.records[i:i + INSERT_CHUNK_SIZE]
        values = [
            (
                r.employee_id, r.date, r.check_in, r.check_out, r.work_hours,
                r.overtime_hours, r.late_in, r.early_out, r.present,
                team_id_by_name.get((r.team_name or "").strip()), payload.source,
            )
            for r in chunk
        ]
        execute_values(
            cur,
            """
            INSERT INTO attendance_records
                (employee_id, date, check_in, check_out, work_hours, overtime_hours,
                 late_in, early_out, present, team_id, source)
            VALUES %s
            ON CONFLICT (employee_id, date) DO UPDATE SET
                check_in = EXCLUDED.check_in, check_out = EXCLUDED.check_out,
                work_hours = EXCLUDED.work_hours, overtime_hours = EXCLUDED.overtime_hours,
                late_in = EXCLUDED.late_in, early_out = EXCLUDED.early_out,
                present = EXCLUDED.present, team_id = EXCLUDED.team_id,
                source = EXCLUDED.source
            """,
            values,
        )
        inserted += len(chunk)

    # Keep employees.current_team_id in sync with the latest attendance
    # snapshot — otherwise /employees?team_id=... and employee->team joins
    # stay NULL even though attendance_records.team_id is correct.
    cur.execute(
        """
        UPDATE employees e SET current_team_id = latest.team_id
        FROM (
            SELECT DISTINCT ON (employee_id) employee_id, team_id
            FROM attendance_records
            ORDER BY employee_id, date DESC
        ) AS latest
        WHERE e.id = latest.employee_id AND latest.team_id IS NOT NULL
        """
    )

    cur.execute(
        "INSERT INTO sync_log (source, records_processed, records_failed, status, notes) VALUES (%s, %s, %s, %s, %s)",
        (f"api_bulk_{payload.source}", inserted, 0, "complete", "via POST /attendance/bulk"),
    )
    conn.commit()
    cur.close()
    conn.close()
    return {"inserted": inserted, "teams_created": len(team_names), "employees_upserted": len(employees)}


@router.post("/leave/bulk")
def bulk_insert_leave(payload: BulkLeaveIn, user=Depends(admin)):
    if not payload.records:
        return {"inserted": 0}

    conn = get_conn()
    cur = conn.cursor()
    values = [(r.employee_id, r.date, r.leave_type, r.status, payload.source) for r in payload.records]
    execute_values(
        cur,
        """
        INSERT INTO leave_records (employee_id, date, leave_type, status, source)
        VALUES %s ON CONFLICT (employee_id, date, leave_type) DO NOTHING
        """,
        values,
    )
    conn.commit()
    cur.close()
    conn.close()
    return {"inserted": len(values)}


@router.post("/attendance/bulk/team")
def update_attendance_teams(
    payload: BulkAttendanceTeamUpdateIn,
    user=Depends(admin),
):

    if not payload.records:
        return {"updated": 0, "skipped": 0}

    conn = get_conn()
    cur = conn.cursor()

    updated = 0
    skipped = 0

    try:
        # Get all teams from the database.
        # Cursor returns dictionary rows: {"id": ..., "name": ...}
        cur.execute("SELECT id, name FROM teams")

        team_id_by_name = {
            row["name"].strip(): row["id"]
            for row in cur.fetchall()
        }

        print("TEAM LOOKUP:")
        print(team_id_by_name)

        # Update each attendance record using employee + date
        # and resolve team_id from team_name.
        for record in payload.records:
            team_name = record.team_name.strip() if record.team_name else None

            if not team_name:
                skipped += 1
                continue

            team_id = team_id_by_name.get(team_name)

            if team_id is None:
                print(f"Team not found: {team_name}")
                skipped += 1
                continue

            cur.execute(
                """
                UPDATE attendance_records
                SET team_id = %s
                WHERE employee_id = %s
                  AND date = %s
                """,
                (
                    team_id,
                    record.employee_id,
                    record.date,
                ),
            )

            updated += cur.rowcount

        conn.commit()

        return {
            "updated": updated,
            "skipped": skipped,
        }

    except Exception:
        conn.rollback()
        raise

    finally:
        cur.close()
        conn.close()
