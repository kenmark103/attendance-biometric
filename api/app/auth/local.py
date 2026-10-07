"""Local email/password routes (/auth)."""
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from app.auth.security import hash_password, verify_password
from app.auth.sessions import (
    clear_refresh_cookie,
    issue_session,
    log_event,
    revoke_all_for_user,
    rotate_session,
)
from app.core.db import get_conn
from app.core.deps import current_user

router = APIRouter(tags=["auth"])

# In-memory sliding-window limiter: 10 attempts/minute/IP.
# Single process only — a second replica would have its own bucket.
# (No Redis in this stack; note as a limitation, don't silently work around.)
_LOGIN_ATTEMPTS: dict[str, deque] = defaultdict(deque)
LOGIN_WINDOW_S = 60
LOGIN_MAX = 10

LOCK_AFTER = 5
LOCK_MINUTES = 15


class LoginIn(BaseModel):
    email: str
    password: str


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str


def _client_ip(request: Request) -> str:
    try:
        return request.client.host if request.client else "unknown"
    except Exception:
        return "unknown"


def _check_rate_limit(ip: str):
    now = time.time()
    bucket = _LOGIN_ATTEMPTS[ip]
    while bucket and now - bucket[0] > LOGIN_WINDOW_S:
        bucket.popleft()
    if len(bucket) >= LOGIN_MAX:
        raise HTTPException(status_code=429, detail="too_many_attempts")
    bucket.append(now)


@router.post("/auth/login")
def login(payload: LoginIn, request: Request, response: Response):
    _check_rate_limit(_client_ip(request))
    email = (payload.email or "").strip().lower()
    if "@" not in email:
        # Same generic body as a bad password — no user enumeration.
        raise HTTPException(status_code=401, detail="invalid_credentials")

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM users WHERE email = %s AND auth_provider = 'local'",
            (email,),
        )
        user = cur.fetchone()

        if user is not None and user["locked_until"] is not None:
            cur.execute("SELECT now() AS now")
            locked = user["locked_until"] > cur.fetchone()["now"]
            if locked:
                conn.rollback()
                raise HTTPException(status_code=401, detail="invalid_credentials")

        ok = verify_password(
            user["password_hash"] if user else None, payload.password or "")
        if not ok:
            if user is not None:
                failed = (user["failed_login_count"] or 0) + 1
                if failed >= LOCK_AFTER:
                    cur.execute(
                        "UPDATE users SET failed_login_count = 0,"
                        " locked_until = now() + (%s || ' minutes')::interval,"
                        " updated_at = now() WHERE id = %s",
                        (str(LOCK_MINUTES), str(user["id"])),
                    )
                else:
                    cur.execute(
                        "UPDATE users SET failed_login_count = %s,"
                        " updated_at = now() WHERE id = %s",
                        (failed, str(user["id"])),
                    )
                log_event(cur, user_id=user["id"], email=email,
                          event="login_fail", provider="local", request=request)
                conn.commit()
            raise HTTPException(status_code=401, detail="invalid_credentials")

        if not user["is_active"]:
            log_event(cur, user_id=user["id"], email=email,
                      event="login_denied", provider="local", request=request,
                      detail="inactive")
            conn.commit()
            raise HTTPException(status_code=401, detail="invalid_credentials")

        cur.execute(
            "UPDATE users SET failed_login_count = 0, locked_until = NULL,"
            " updated_at = now() WHERE id = %s",
            (str(user["id"]),),
        )
        log_event(cur, user_id=user["id"], email=email,
                  event="login_ok", provider="local", request=request)
        conn.commit()
        return issue_session(conn, user, request, response)
    finally:
        conn.close()


@router.post("/auth/refresh")
def refresh(request: Request, response: Response):
    conn = get_conn()
    try:
        return rotate_session(conn, request, response)
    finally:
        conn.close()


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response):
    from app.auth.security import hash_refresh
    raw = request.cookies.get("refresh_token")
    conn = get_conn()
    try:
        cur = conn.cursor()
        if raw:
            cur.execute(
                "SELECT family_id, user_id FROM refresh_tokens WHERE token_hash = %s",
                (hash_refresh(raw),),
            )
            row = cur.fetchone()
            if row:
                cur.execute(
                    "UPDATE refresh_tokens SET revoked_at = now()"
                    " WHERE family_id = %s AND revoked_at IS NULL",
                    (str(row["family_id"]),),
                )
                log_event(cur, user_id=row["user_id"], email=None,
                          event="logout", request=request)
                conn.commit()
        cur.close()
    finally:
        conn.close()
    clear_refresh_cookie(response)
    return Response(status_code=204)


@router.get("/auth/me")
def me(user=Depends(current_user)):
    from app.auth.sessions import user_public
    return user_public(user)


@router.post("/auth/change-password")
def change_password(payload: ChangePasswordIn, request: Request,
                    response: Response, user=Depends(current_user)):
    if user["auth_provider"] != "local":
        raise HTTPException(status_code=400, detail="sso_managed_password")
    new = payload.new_password or ""
    if len(new) < 12 or len(new) > 128:
        raise HTTPException(status_code=400, detail="password_must_be_12_to_128_chars")
    if not verify_password(user["password_hash"], payload.current_password or ""):
        raise HTTPException(status_code=401, detail="invalid_credentials")
    if new == (payload.current_password or "") or new.lower() == (user["email"] or "").lower():
        raise HTTPException(status_code=400, detail="password_not_acceptable")

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE users SET password_hash = %s, must_change_password = FALSE,"
            " failed_login_count = 0, locked_until = NULL, updated_at = now()"
            " WHERE id = %s",
            (hash_password(new), str(user["id"])),
        )
        log_event(cur, user_id=user["id"], email=user["email"],
                  event="password_changed", provider="local", request=request)
        conn.commit()
        cur.execute("SELECT * FROM users WHERE id = %s", (str(user["id"]),))
        fresh = cur.fetchone()
        cur.close()
        # Other devices are signed out; this device stays signed in.
        revoke_all_for_user(conn, user["id"])
        return issue_session(conn, fresh, request, response)
    finally:
        conn.close()
