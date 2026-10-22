"""Admin-only user and audit administration."""
import secrets
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app.auth.audit import audit
from app.auth.security import hash_password
from app.auth.sessions import revoke_all_for_user
from app.core.db import get_db
from app.core.deps import ROLE_ADMIN, ROLE_VIEWER, require_admin


router = APIRouter(prefix="/admin", tags=["admin"])
VALID_ROLES = (ROLE_VIEWER, ROLE_ADMIN)


class CreateUserIn(BaseModel):
    email: str
    display_name: Optional[str] = None
    role: str = ROLE_VIEWER
    password: str | None = None


class PatchUserIn(BaseModel):
    display_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


def _public(row) -> dict:
    return {
        "id": str(row["id"]), "email": row["email"], "display_name": row.get("display_name"),
        "role": row["role"], "auth_provider": row["auth_provider"],
        "is_active": bool(row["is_active"]),
        "must_change_password": bool(row["must_change_password"]),
        "last_login_at": str(row["last_login_at"]) if row.get("last_login_at") else None,
        "created_at": str(row["created_at"]) if row.get("created_at") else None,
    }


def _assert_last_admin(cur, target, new_role: str | None, is_active: bool | None) -> None:
    remains_admin = (new_role or target["role"]) == ROLE_ADMIN and (target["is_active"] if is_active is None else is_active)
    if target["role"] == ROLE_ADMIN and target["is_active"] and not remains_admin:
        cur.execute("SELECT COUNT(*) AS n FROM users WHERE role = %s AND is_active = TRUE AND id <> %s",
                    (ROLE_ADMIN, str(target["id"])))
        if cur.fetchone()["n"] == 0:
            raise HTTPException(400, "cannot_remove_last_admin")


@router.get("/users")
def list_users(user=Depends(require_admin), conn=Depends(get_db)):
    cur = conn.cursor()
    cur.execute("SELECT * FROM users ORDER BY email")
    rows = [_public(row) for row in cur.fetchall()]
    cur.close()
    return rows


@router.post("/users")
def create_user(payload: CreateUserIn, request: Request, user=Depends(require_admin), conn=Depends(get_db)):
    email = (payload.email or "").strip().lower()
    if "@" not in email or payload.role not in VALID_ROLES:
        raise HTTPException(400, "invalid_user")
    password = payload.password or secrets.token_urlsafe(12)
    if len(password) < 12 or password.lower() == email:
        raise HTTPException(400, "password_not_acceptable")
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO users (email, display_name, role, auth_provider, password_hash, must_change_password) "
            "VALUES (%s,%s,%s,'local',%s,%s) RETURNING *",
            (email, payload.display_name, payload.role, hash_password(password), payload.password is None),
        )
        row = cur.fetchone()
        audit(cur, actor=user, request=request, action="user.create", entity_type="user", entity_id=row["id"],
              after={"email": email, "role": payload.role, "auth_provider": "local"})
        conn.commit()
    except Exception as exc:
        conn.rollback()
        if "unique" in str(exc).lower():
            raise HTTPException(409, "email_exists")
        raise
    finally:
        cur.close()
    out = _public(row)
    if payload.password is None:
        out["temporary_password"] = password
    return out


@router.patch("/users/{user_id}")
def patch_user(user_id: str, payload: PatchUserIn, request: Request,
               user=Depends(require_admin), conn=Depends(get_db)):
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    target = cur.fetchone()
    if target is None:
        cur.close()
        raise HTTPException(404, "not_found")
    if str(target["id"]) == str(user["id"]):
        if payload.role is not None and payload.role != target["role"]:
            raise HTTPException(400, "cannot_demote_self")
        if payload.is_active is False:
            raise HTTPException(400, "cannot_deactivate_self")
    if payload.role is not None and payload.role not in VALID_ROLES:
        raise HTTPException(400, "invalid_role")
    _assert_last_admin(cur, target, payload.role, payload.is_active)
    updates, values = [], []
    if payload.display_name is not None:
        updates.append("display_name = %s"); values.append(payload.display_name)
    if payload.role is not None:
        updates.append("role = %s"); values.append(payload.role)
    if payload.is_active is not None:
        updates.append("is_active = %s"); values.append(payload.is_active)
    if not updates:
        raise HTTPException(400, "nothing_to_update")
    values.append(str(target["id"]))
    cur.execute(f"UPDATE users SET {', '.join(updates)}, updated_at = now() WHERE id = %s RETURNING *", values)
    row = cur.fetchone()
    if payload.role is not None or payload.is_active is False:
        revoke_all_for_user(conn, target["id"], cur=cur)
    action = "user.role_change" if payload.role is not None else ("user.deactivate" if payload.is_active is False else "user.update")
    audit(cur, actor=user, request=request, action=action, entity_type="user", entity_id=target["id"],
          before={"role": target["role"], "is_active": target["is_active"], "display_name": target.get("display_name")},
          after={"role": row["role"], "is_active": row["is_active"], "display_name": row.get("display_name")})
    conn.commit()
    cur.close()
    return _public(row)


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: str, request: Request, user=Depends(require_admin), conn=Depends(get_db)):
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    target = cur.fetchone()
    if target is None:
        cur.close()
        raise HTTPException(404, "not_found")
    if target["auth_provider"] != "local":
        cur.close()
        raise HTTPException(400, "sso_managed_password")
    password = secrets.token_urlsafe(12)
    cur.execute("UPDATE users SET password_hash = %s, must_change_password = TRUE, failed_login_count = 0, "
                "locked_until = NULL, updated_at = now() WHERE id = %s", (hash_password(password), user_id))
    revoke_all_for_user(conn, target["id"], cur=cur)
    audit(cur, actor=user, request=request, action="user.password_reset", entity_type="user", entity_id=target["id"])
    conn.commit()
    cur.close()
    return {"temporary_password": password}


def _range_filter(column: str, date_from: datetime | None, date_to: datetime | None, clauses: list, params: list):
    if date_from:
        clauses.append(f"{column} >= %s"); params.append(date_from)
    if date_to:
        clauses.append(f"{column} <= %s"); params.append(date_to)


@router.get("/auth-events")
def list_auth_events(email: str | None = None, date_from: datetime | None = None,
                     date_to: datetime | None = None, limit: int = Query(100, ge=1, le=500),
                     offset: int = Query(0, ge=0), user=Depends(require_admin), conn=Depends(get_db)):
    clauses, params = [], []
    if email:
        clauses.append("email ILIKE %s"); params.append(f"%{email}%")
    _range_filter("ts", date_from, date_to, clauses, params)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) AS n FROM auth_events {where}", params); total = cur.fetchone()["n"]
    cur.execute(f"SELECT id, ts, event, method, user_id, email, entra_oid, ip, user_agent, detail "
                f"FROM auth_events {where} ORDER BY ts DESC, id DESC LIMIT %s OFFSET %s", [*params, limit, offset])
    rows = [{**row, "ts": str(row["ts"]), "user_id": str(row["user_id"]) if row["user_id"] else None}
            for row in cur.fetchall()]
    cur.close()
    return {"total": total, "items": rows}


@router.get("/audit-log")
def list_audit_log(actor: str | None = None, action: str | None = None, date_from: datetime | None = None,
                   date_to: datetime | None = None, limit: int = Query(100, ge=1, le=500),
                   offset: int = Query(0, ge=0), user=Depends(require_admin), conn=Depends(get_db)):
    clauses, params = [], []
    if actor:
        clauses.append("actor_email ILIKE %s"); params.append(f"%{actor}%")
    if action:
        clauses.append("action = %s"); params.append(action)
    _range_filter("ts", date_from, date_to, clauses, params)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) AS n FROM audit_log {where}", params); total = cur.fetchone()["n"]
    cur.execute(f"SELECT id, ts, actor_email, action, entity_type, entity_id, before, after, ip, request_id "
                f"FROM audit_log {where} ORDER BY ts DESC, id DESC LIMIT %s OFFSET %s", [*params, limit, offset])
    rows = [{**row, "ts": str(row["ts"])} for row in cur.fetchall()]
    cur.close()
    return {"total": total, "items": rows}
