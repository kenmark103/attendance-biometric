from datetime import date
from typing import Optional, List

import jwt
import os
import psycopg2
import psycopg2.extras
from psycopg2.extras import execute_values
from fastapi import FastAPI, Query, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://attendance:attendance@db:5432/attendance"
)
AUTH_SECRET = os.environ.get("AUTH_SECRET")  # shared with auth-service
# Local dev escape hatch: leave AUTH_REQUIRED unset/false while you're
# iterating on schema/data, flip it on once the auth-service flow works.
AUTH_REQUIRED = os.environ.get("AUTH_REQUIRED", "false").lower() == "true"

app = FastAPI(title="Attendance System API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten before this leaves local dev
    allow_methods=["*"],
    allow_headers=["*"],
)


class AttendanceRecordIn(BaseModel):
    employee_id: str
    employee_name: str
    date: date
    check_in: Optional[str] = None
    check_out: Optional[str] = None
    work_hours: float = 0
    overtime_hours: float = 0
    late_in: bool = False
    early_out: bool = False
    present: bool = False
    team_name: str


class BulkAttendanceIn(BaseModel):
    source: str
    records: List[AttendanceRecordIn]


class LeaveRecordIn(BaseModel):
    employee_id: str
    date: date
    leave_type: str
    status: str = "approved"


class BulkLeaveIn(BaseModel):
    source: str = "zoho"
    records: List[LeaveRecordIn]

class AttendanceTeamUpdate(BaseModel):
    employee_id: str
    date: date
    team_name: str | None = None


class BulkAttendanceTeamUpdateIn(BaseModel):
    records: list[AttendanceTeamUpdate]


def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def get_current_user(request: Request):
    """
    Verifies the token issued by auth-service (shared HS256 secret —
    fine for two services you control; swap to asymmetric/JWKS if this
    boundary ever crosses a trust boundary you don't control).

    If AUTH_REQUIRED is false, returns a stub admin user so the rest of
    the API is usable while auth is still being wired up.
    """
    if not AUTH_REQUIRED:
        return {"email": "dev@local", "role": "admin", "employee_id": None}

    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = auth_header.removeprefix("Bearer ")
    try:
        return jwt.decode(token, AUTH_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")


@app.get("/health")
def health():
    return {"status": "ok", "auth_required": AUTH_REQUIRED}


@app.get("/teams")
def list_teams(user=Depends(get_current_user)):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM teams ORDER BY name")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


@app.get("/employees")
def list_employees(team_id: Optional[int] = None, user=Depends(get_current_user)):
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


@app.get("/attendance")
def get_attendance(
    employee_id: Optional[str] = None,
    team_id: Optional[int] = None,
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    user=Depends(get_current_user),
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
        LIMIT 1000
        """,
        params,
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


@app.get("/leave")
def get_leave(
    employee_id: Optional[str] = None,
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    user=Depends(get_current_user),
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
        LIMIT 1000
        """,
        params,
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


@app.get("/holidays")
def get_holidays(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    user=Depends(get_current_user),
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
    cur.execute(f"SELECT id, date, name, source FROM holidays {where} ORDER BY date")
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



def require_admin(user):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only admin/service accounts may write attendance data")


@app.post("/attendance/bulk")
def bulk_insert_attendance(payload: BulkAttendanceIn, user=Depends(get_current_user)):
    require_admin(user)
    if payload.source not in ALLOWED_SOURCES:
        raise HTTPException(status_code=400, detail=f"source must be one of {sorted(ALLOWED_SOURCES)}")
    if not payload.records:
        return {"inserted": 0, "teams_created": 0, "employees_upserted": 0}

    conn = get_conn()
    cur = conn.cursor()

    # Teams and employees have to exist before attendance can reference
    # them (foreign keys) — same Zoho-first ordering discussed earlier,
    # just enforced here structurally rather than by convention.
    team_names = sorted({r.team_name.strip() for r in payload.records if r.team_name})
    execute_values(
        cur, "INSERT INTO teams (name) VALUES %s ON CONFLICT (name) DO NOTHING",
        [(t,) for t in team_names],
    )
    cur.execute("SELECT id, name FROM teams")
    team_id_by_name = {name: tid for tid, name in cur.fetchall()}

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
                team_id_by_name.get(r.team_name.strip()), payload.source,
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

    cur.execute(
        "INSERT INTO sync_log (source, records_processed, records_failed, status, notes) VALUES (%s, %s, %s, %s, %s)",
        (f"api_bulk_{payload.source}", inserted, 0, "complete", "via POST /attendance/bulk"),
    )
    conn.commit()
    cur.close()
    conn.close()
    return {"inserted": inserted, "teams_created": len(team_names), "employees_upserted": len(employees)}


@app.post("/leave/bulk")
def bulk_insert_leave(payload: BulkLeaveIn, user=Depends(get_current_user)):
    require_admin(user)
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

@app.post("/attendance/bulk/team")
def update_attendance_teams(
    payload: BulkAttendanceTeamUpdateIn,
    user=Depends(get_current_user),
):
    require_admin(user)

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