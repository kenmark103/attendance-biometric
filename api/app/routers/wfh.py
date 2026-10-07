"""WFH approvals: team-lead manual override for approved work-from-home.
Not reported via Zoho/biometric. Counts as present for attendance rate."""
from datetime import date
from typing import Optional

import psycopg2
import psycopg2.extras
from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.db import get_conn
from app.core.deps import viewer
from app.routers.schemas import WfhIn

router = APIRouter(tags=["wfh"])


@router.get("/wfh")
def list_wfh(
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
        clauses.append("w.employee_id = %s"); params.append(employee_id)
    if date_from:
        clauses.append("w.date >= %s"); params.append(date_from)
    if date_to:
        clauses.append("w.date <= %s"); params.append(date_to)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cur.execute(
        f"""
        SELECT w.id, w.employee_id, e.name AS employee_name, w.date, w.reason, w.approved_by, w.created_at,
               t.name AS team_name
        FROM wfh_approvals w
        JOIN employees e ON e.id = w.employee_id
        LEFT JOIN teams t ON t.id = e.current_team_id
        {where}
        ORDER BY w.date DESC LIMIT %s OFFSET %s
        """,
        [*params, limit, offset],
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


@router.post("/wfh")
def create_wfh(payload: WfhIn, user=Depends(viewer)):
    # allow admin/manager always; for team_lead, verify they lead employee's team (best-effort)
    if user.get("role") not in ("admin", "manager"):
        # try team_lead path: look up employee team and compare lead
        conn = get_conn()
        cur = conn.cursor()
        try:
            cur.execute("SELECT current_team_id FROM employees WHERE id = %s", (payload.employee_id,))
            erow = cur.fetchone()
            if erow and erow.get("current_team_id"):
                cur.execute("SELECT lead_employee_id FROM teams WHERE id = %s", (erow["current_team_id"],))
                trow = cur.fetchone()
                is_lead = trow and trow.get("lead_employee_id") == user.get("employee_id")
                if not is_lead:
                    raise HTTPException(status_code=403, detail="Only team lead of this employee may approve WFH")
            else:
                raise HTTPException(status_code=403, detail="Only admin/manager may approve WFH")
        finally:
            cur.close(); conn.close()
    conn = get_conn()
    cur = conn.cursor()
    # resolve actor id for audit
    cur.execute("SELECT id FROM users WHERE email = %s", (user.get("email"),))
    actor = cur.fetchone()
    actor_id = actor["id"] if actor else None
    try:
        cur.execute(
            "INSERT INTO wfh_approvals (employee_id, date, approved_by, reason) VALUES (%s,%s,%s,%s) ON CONFLICT (employee_id,date) DO UPDATE SET reason=EXCLUDED.reason RETURNING id",
            (payload.employee_id, payload.date, actor_id, payload.reason),
        )
        wid = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO audit_log (actor_user_id, target_employee_id, action, after_value) VALUES (%s,%s,%s,%s)",
            (actor_id, payload.employee_id, "wfh_approve", psycopg2.extras.Json({"date": str(payload.date), "reason": payload.reason})),
        )
        conn.commit()
        return {"id": wid, "status": "approved"}
    except psycopg2.Error as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cur.close(); conn.close()


@router.delete("/wfh/{wfh_id}")
def delete_wfh(wfh_id: int, user=Depends(viewer)):
    if user.get("role") not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Only admin/manager may revoke WFH")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT employee_id, date FROM wfh_approvals WHERE id = %s", (wfh_id,))
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="Not found")
    cur.execute("DELETE FROM wfh_approvals WHERE id = %s", (wfh_id,))
    cur.execute("SELECT id FROM users WHERE email = %s", (user.get("email"),))
    actor = cur.fetchone()
    actor_id = actor["id"] if actor else None
    cur.execute(
        "INSERT INTO audit_log (actor_user_id, target_employee_id, action, before_value) VALUES (%s,%s,%s,%s)",
        (actor_id, row["employee_id"], "wfh_revoke", psycopg2.extras.Json({"date": str(row["date"])})),
    )
    conn.commit()
    cur.close(); conn.close()
    return {"deleted": wfh_id}
