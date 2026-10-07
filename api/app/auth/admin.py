"""Admin user management. All require_role('admin').

`users` (system logins) is distinct from `employees` (attendance subjects):
an admin here may or may not also be a tracked employee. Roles set here
for `entra` users are overwritten on their next SSO login if Entra
supplies a role — Entra is the source of truth then.
"""
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app.auth.security import hash_password
from app.auth.sessions import log_event, revoke_all_for_user
from app.core.db import get_conn
from app.core.deps import require_role

router = APIRouter(tags=["admin"])
admin_only = require_role('admin')

VALID_ROLES = ('admin', 'manager', 'viewer')
VALID_PROVIDERS = ('local', 'entra')


class CreateUserIn(BaseModel):
    email: str
    display_name: Optional[str] = None
    role: str = 'viewer'
    auth_provider: str = 'local'
    password: Optional[str] = None


class PatchUserIn(BaseModel):
    display_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


def _row_public(row) -> dict:
    return {
        "id": str(row["id"]),
        "email": row["email"],
        "display_name": row.get("display_name"),
        "role": row["role"],
        "provider": row["auth_provider"],
        "is_active": bool(row["is_active"]),
        "must_change_password": bool(row["must_change_password"]),
        "last_login_at": str(row["last_login_at"]) if row.get("last_login_at") else None,
        "created_at": str(row.get("created_at")) if row.get("created_at") else None,
    }


@router.get("/users")
def list_users(user=Depends(admin_only)):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users ORDER BY email")
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()
    return [_row_public(r) for r in rows]


@router.post("/users")
def create_user(payload: CreateUserIn, request: Request, user=Depends(admin_only)):
    email = (payload.email or "").strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=400, detail="invalid_email")
    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="invalid_role")
    if payload.auth_provider not in VALID_PROVIDERS:
        raise HTTPException(status_code=400, detail="invalid_provider")

    temporary_password = None
    password_hash = None
    must_change = False
    if payload.auth_provider == "local":
        if payload.password:
            if len(payload.password) < 12 or len(payload.password) > 128:
                raise HTTPException(status_code=400,
                                    detail="password_must_be_12_to_128_chars")
            password_hash = hash_password(payload.password)
        else:
            temporary_password = secrets.token_urlsafe(12)
            password_hash = hash_password(temporary_password)
            must_change = True

    conn = get_conn()
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO users (email, display_name, role, auth_provider,"
                " password_hash, must_change_password)"
                " VALUES (%s,%s,%s,%s,%s,%s) RETURNING *",
                (email, payload.display_name, payload.role,
                 payload.auth_provider, password_hash, must_change),
            )
            row = cur.fetchone()
        except Exception as e:
            conn.rollback()
            if "unique" in str(e).lower():
                raise HTTPException(status_code=409, detail="email_exists")
            raise
        log_event(cur, user_id=user["id"], email=email, event="user_created",
                  provider=payload.auth_provider, request=request,
                  detail=f"role={payload.role}")
        conn.commit()
        cur.close()
    finally:
        conn.close()

    out = _row_public(row)
    if temporary_password:
        # Shown once. Give it to the user directly.
        out["temporary_password"] = temporary_password
    return out


@router.patch("/users/{user_id}")
def patch_user(user_id: str, payload: PatchUserIn, request: Request,
               user=Depends(admin_only)):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        target = cur.fetchone()
        if target is None:
            raise HTTPException(status_code=404, detail="not_found")

        is_self = str(target["id"]) == str(user["id"])
        updates, params = [], []
        if payload.display_name is not None:
            updates.append("display_name = %s")
            params.append(payload.display_name)
        if payload.role is not None:
            if payload.role not in VALID_ROLES:
                raise HTTPException(status_code=400, detail="invalid_role")
            if is_self and payload.role != target["role"]:
                raise HTTPException(status_code=400, detail="cannot_demote_self")
            updates.append("role = %s")
            params.append(payload.role)
        if payload.is_active is not None:
            if is_self and payload.is_active is False:
                raise HTTPException(status_code=400, detail="cannot_deactivate_self")
            if payload.is_active is False and target["role"] == "admin" \
                    and target["is_active"]:
                cur.execute(
                    "SELECT COUNT(*) AS n FROM users"
                    " WHERE role = 'admin' AND is_active = TRUE AND id <> %s",
                    (str(target["id"]),),
                )
                if cur.fetchone()["n"] == 0:
                    raise HTTPException(status_code=400, detail="cannot_remove_last_admin")
            updates.append("is_active = %s")
            params.append(payload.is_active)
        if not updates:
            raise HTTPException(status_code=400, detail="nothing_to_update")
        updates.append("updated_at = now()")
        params.append(str(target["id"]))
        cur.execute(
            f"UPDATE users SET {', '.join(updates)} WHERE id = %s RETURNING *",
            params,
        )
        row = cur.fetchone()
        if payload.is_active is False:
            revoke_all_for_user(conn, target["id"])
            log_event(cur, user_id=user["id"], email=target["email"],
                      event="user_deactivated", request=request)
        else:
            log_event(cur, user_id=user["id"], email=target["email"],
                      event="user_updated", request=request,
                      detail=",".join(
                          k for k, v in payload.model_dump(
                              exclude_unset=True).items() if v is not None))
        conn.commit()
        cur.close()
        return _row_public(row)
    finally:
        conn.close()


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: str, request: Request, user=Depends(admin_only)):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        target = cur.fetchone()
        if target is None:
            raise HTTPException(status_code=404, detail="not_found")
        if target["auth_provider"] != "local":
            raise HTTPException(status_code=400, detail="sso_managed_password")
        temporary_password = secrets.token_urlsafe(12)
        cur.execute(
            "UPDATE users SET password_hash = %s, must_change_password = TRUE,"
            " failed_login_count = 0, locked_until = NULL, updated_at = now()"
            " WHERE id = %s",
            (hash_password(temporary_password), str(target["id"])),
        )
        log_event(cur, user_id=user["id"], email=target["email"],
                  event="password_reset", request=request)
        conn.commit()
        cur.close()
        revoke_all_for_user(conn, target["id"])
    finally:
        conn.close()
    return {"temporary_password": temporary_password}


@router.get("/auth/events")
def list_auth_events(limit: int = Query(100, ge=1, le=500),
                     user=Depends(admin_only)):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, at, user_id, email, event, provider, ip, user_agent, detail"
            " FROM auth_events ORDER BY id DESC LIMIT %s",
            (limit,),
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()
    return [
        {**r, "at": str(r["at"]),
         "user_id": str(r["user_id"]) if r["user_id"] else None}
        for r in rows
    ]
