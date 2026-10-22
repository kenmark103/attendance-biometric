"""Admin-managed WFH policies. WFH affects metrics only, never ingestion."""
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, model_validator

from app.auth.audit import audit
from app.core.db import get_db
from app.core.deps import require_admin, require_viewer

router = APIRouter(prefix="/admin/wfh", tags=["wfh"])


class PolicyIn(BaseModel):
    employee_id: str
    type: Literal["temporary", "default"]
    start_date: date
    end_date: date | None = None
    note: str | None = None

    @model_validator(mode="after")
    def dates_are_valid(self):
        if self.type == "temporary" and (self.end_date is None or self.end_date < self.start_date):
            raise ValueError("temporary policies require end_date on or after start_date")
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must not precede start_date")
        return self


class PolicyPatch(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    note: str | None = None


class RecallIn(BaseModel):
    employee_id: str
    date: date
    reason: str | None = None


def _employee_exists(cur, employee_id: str) -> None:
    cur.execute("SELECT 1 FROM employees WHERE id = %s", (employee_id,))
    if cur.fetchone() is None:
        raise HTTPException(422, "unknown_employee")


def _overlap(cur, payload: PolicyIn, ignore_id: int | None = None):
    clauses = ["employee_id = %s", "status <> 'revoked'", "start_date <= %s", "(end_date IS NULL OR end_date >= %s)"]
    params = [payload.employee_id, payload.end_date or date.max, payload.start_date]
    if ignore_id is not None:
        clauses.append("id <> %s"); params.append(ignore_id)
    cur.execute(f"SELECT id FROM wfh_policies WHERE {' AND '.join(clauses)} ORDER BY id LIMIT 1", params)
    row = cur.fetchone()
    if row:
        raise HTTPException(409, f"conflicts_with_policy:{row['id']}")


@router.get("/policies")
def list_policies(employee_id: str | None = None, status: str | None = None,
                  active_on: date | None = Query(None), user=Depends(require_viewer), conn=Depends(get_db)):
    clauses, params = [], []
    if employee_id: clauses.append("p.employee_id = %s"); params.append(employee_id)
    if status: clauses.append("p.status = %s"); params.append(status)
    if active_on: clauses.append("p.start_date <= %s AND (p.end_date IS NULL OR p.end_date >= %s)"); params += [active_on, active_on]
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cur = conn.cursor()
    cur.execute(f"SELECT p.*, e.name AS employee_name FROM wfh_policies p JOIN employees e ON e.id=p.employee_id {where} ORDER BY p.start_date DESC, p.id DESC", params)
    rows = cur.fetchall(); cur.close()
    return rows


@router.post("/policies")
def create_policy(payload: PolicyIn, request: Request, user=Depends(require_admin), conn=Depends(get_db)):
    cur = conn.cursor()
    try:
        _employee_exists(cur, payload.employee_id); _overlap(cur, payload)
        cur.execute("INSERT INTO wfh_policies (employee_id,type,start_date,end_date,note,created_by) VALUES (%s,%s,%s,%s,%s,%s) RETURNING *", (payload.employee_id, payload.type, payload.start_date, payload.end_date, payload.note, str(user["id"])))
        row = cur.fetchone()
        audit(cur, actor=user, request=request, action="wfh.create", entity_type="wfh_policy", entity_id=row["id"], after={"employee_id": payload.employee_id, "type": payload.type, "start_date": str(payload.start_date), "end_date": str(payload.end_date) if payload.end_date else None})
        conn.commit(); return row
    except Exception:
        conn.rollback(); raise
    finally: cur.close()


@router.patch("/policies/{policy_id}")
def patch_policy(policy_id: int, payload: PolicyPatch, request: Request, user=Depends(require_admin), conn=Depends(get_db)):
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM wfh_policies WHERE id=%s FOR UPDATE", (policy_id,)); before = cur.fetchone()
        if before is None: raise HTTPException(404, "not_found")
        if before["status"] == "revoked": raise HTTPException(409, "revoked_policy_cannot_be_edited")
        start, end = payload.start_date or before["start_date"], payload.end_date if payload.end_date is not None else before["end_date"]
        candidate = PolicyIn(employee_id=before["employee_id"], type=before["type"], start_date=start, end_date=end, note=payload.note if payload.note is not None else before["note"])
        _overlap(cur, candidate, policy_id)
        cur.execute("UPDATE wfh_policies SET start_date=%s,end_date=%s,note=%s,updated_at=now() WHERE id=%s RETURNING *", (start,end,candidate.note,policy_id)); row=cur.fetchone()
        audit(cur, actor=user, request=request, action="wfh.update", entity_type="wfh_policy", entity_id=policy_id, before={"status":before["status"]}, after={"start_date":str(row["start_date"]),"end_date":str(row["end_date"]) if row["end_date"] else None})
        conn.commit(); return row
    except Exception:
        conn.rollback(); raise
    finally: cur.close()


@router.post("/policies/{policy_id}/approve")
def approve_policy(policy_id: int, request: Request, user=Depends(require_admin), conn=Depends(get_db)):
    cur=conn.cursor()
    try:
        cur.execute("UPDATE wfh_policies SET status='approved',approved_by=%s,approved_at=now(),updated_at=now() WHERE id=%s AND status='pending' RETURNING *", (str(user["id"]),policy_id)); row=cur.fetchone()
        if row is None: raise HTTPException(409,"policy_not_pending_or_missing")
        audit(cur,actor=user,request=request,action="wfh.approve",entity_type="wfh_policy",entity_id=policy_id,after={"status":"approved"}); conn.commit(); return row
    except Exception: conn.rollback(); raise
    finally: cur.close()


@router.post("/policies/{policy_id}/revoke")
def revoke_policy(policy_id: int, request: Request, user=Depends(require_admin), conn=Depends(get_db)):
    cur=conn.cursor()
    try:
        cur.execute("UPDATE wfh_policies SET status='revoked',updated_at=now() WHERE id=%s AND status <> 'revoked' RETURNING *", (policy_id,)); row=cur.fetchone()
        if row is None: raise HTTPException(404,"not_found")
        audit(cur,actor=user,request=request,action="wfh.revoke",entity_type="wfh_policy",entity_id=policy_id,after={"status":"revoked"}); conn.commit(); return row
    except Exception: conn.rollback(); raise
    finally: cur.close()


@router.get("/recalls")
def list_recalls(user=Depends(require_viewer), conn=Depends(get_db)):
    cur=conn.cursor(); cur.execute("SELECT r.*,e.name AS employee_name FROM wfh_recalls r JOIN employees e ON e.id=r.employee_id ORDER BY date DESC,id DESC"); rows=cur.fetchall();cur.close();return rows


@router.post("/recalls")
def create_recall(payload: RecallIn, request: Request, user=Depends(require_admin), conn=Depends(get_db)):
    cur=conn.cursor()
    try:
        _employee_exists(cur,payload.employee_id)
        cur.execute("SELECT 1 FROM wfh_policies WHERE employee_id=%s AND status='approved' AND start_date<=%s AND (end_date IS NULL OR end_date>=%s) LIMIT 1",(payload.employee_id,payload.date,payload.date))
        if cur.fetchone() is None: raise HTTPException(409,"no_active_wfh_policy_for_recall")
        cur.execute("INSERT INTO wfh_recalls (employee_id,date,reason,created_by) VALUES (%s,%s,%s,%s) RETURNING *",(payload.employee_id,payload.date,payload.reason,str(user["id"])));row=cur.fetchone()
        audit(cur,actor=user,request=request,action="wfh.recall_create",entity_type="wfh_recall",entity_id=row["id"],after={"employee_id":payload.employee_id,"date":str(payload.date)});conn.commit();return row
    except Exception: conn.rollback();raise
    finally:cur.close()


@router.delete("/recalls/{recall_id}")
def delete_recall(recall_id:int,request:Request,user=Depends(require_admin),conn=Depends(get_db)):
    cur=conn.cursor()
    try:
        cur.execute("DELETE FROM wfh_recalls WHERE id=%s RETURNING *",(recall_id,));row=cur.fetchone()
        if row is None: raise HTTPException(404,"not_found")
        audit(cur,actor=user,request=request,action="wfh.recall_delete",entity_type="wfh_recall",entity_id=recall_id,before={"employee_id":row["employee_id"],"date":str(row["date"])});conn.commit();return {"deleted":recall_id}
    except Exception: conn.rollback();raise
    finally:cur.close()
