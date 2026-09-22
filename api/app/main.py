from datetime import date
from typing import Optional

import jwt
import os
import psycopg2
import psycopg2.extras
from fastapi import FastAPI, Query, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

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
            'SELECT id, name, "current_role", "current_shift" FROM employees WHERE current_team_id = %s ORDER BY name',
            (team_id,),
        )
    else:
        cur.execute('SELECT id, name, "current_role", "current_shift", status FROM employees ORDER BY name')
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
        LIMIT 10000
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
        LIMIT 10000
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
