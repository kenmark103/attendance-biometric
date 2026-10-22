"""Local-login, refresh, logout, and current-user routes."""
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from app.auth.security import hash_password, password_needs_rehash, verify_password
from app.auth.sessions import (
    clear_refresh_cookie,
    issue_session,
    log_event,
    revoke_all_for_user,
    rotate_session,
    user_public,
)
from app.core import settings
from app.core.db import get_db
from app.core.deps import current_user


router = APIRouter(tags=["auth"])
_LOGIN_ATTEMPTS: dict[str, deque] = defaultdict(deque)
LOGIN_WINDOW_SECONDS = 60
LOGIN_MAX_PER_WINDOW = 10


class LoginIn(BaseModel):
    email: str
    password: str


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _check_rate_limit(ip: str) -> None:
    now = time.time()
    bucket = _LOGIN_ATTEMPTS[ip]
    while bucket and now - bucket[0] > LOGIN_WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= LOGIN_MAX_PER_WINDOW:
        raise HTTPException(status_code=429, detail="too_many_attempts")
    bucket.append(now)


def _invalid_credentials() -> HTTPException:
    return HTTPException(status_code=401, detail="invalid_credentials")


@router.get("/auth/config")
def auth_config():
    return {
        "entra_enabled": bool(settings.ENTRA_ENABLED and settings.entra_configured()),
        "local_auth_enabled": settings.LOCAL_AUTH_ENABLED,
        "idle_logout_minutes": settings.IDLE_LOGOUT_MINUTES,
        "idle_warning_seconds": settings.IDLE_WARNING_SECONDS,
        "support_contact_text": settings.SUPPORT_CONTACT_TEXT,
    }


@router.post("/auth/login")
def login(payload: LoginIn, request: Request, response: Response, conn=Depends(get_db)):
    if not settings.LOCAL_AUTH_ENABLED:
        raise HTTPException(status_code=404, detail="local_auth_disabled")
    _check_rate_limit(_client_ip(request))
    email = (payload.email or "").strip().lower()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email = %s AND auth_provider = 'local'", (email,))
    user = cur.fetchone()
    now_row = None
    if user and user["locked_until"] is not None:
        cur.execute("SELECT now() AS now")
        now_row = cur.fetchone()["now"]
        if user["locked_until"] > now_row:
            log_event(cur, user_id=user["id"], email=email, event="login_failed",
                      method="local", request=request, detail="locked")
            conn.commit()
            raise _invalid_credentials()

    # This always verifies a hash, even if the email is malformed, unknown, or
    # belongs to an Entra account.
    ok = verify_password(user["password_hash"] if user else None, payload.password or "")
    if not email or "@" not in email or not ok:
        if user:
            failed = (user["failed_login_count"] or 0) + 1
            if failed >= settings.LOGIN_MAX_FAILED_ATTEMPTS:
                cur.execute(
                    "UPDATE users SET failed_login_count = 0, locked_until = now() + (%s || ' minutes')::interval, "
                    "updated_at = now() WHERE id = %s",
                    (str(settings.LOGIN_LOCKOUT_MINUTES), str(user["id"])),
                )
                log_event(cur, user_id=user["id"], email=email, event="lockout",
                          method="local", request=request)
            else:
                cur.execute("UPDATE users SET failed_login_count = %s, updated_at = now() WHERE id = %s",
                            (failed, str(user["id"])))
                log_event(cur, user_id=user["id"], email=email, event="login_failed",
                          method="local", request=request)
            conn.commit()
        else:
            conn.rollback()
        raise _invalid_credentials()

    if not user["is_active"]:
        log_event(cur, user_id=user["id"], email=email, event="login_denied_inactive",
                  method="local", request=request)
        conn.commit()
        raise _invalid_credentials()

    updates = "failed_login_count = 0, locked_until = NULL, updated_at = now()"
    params = []
    if password_needs_rehash(user["password_hash"]):
        updates += ", password_hash = %s"
        params.append(hash_password(payload.password))
    params.append(str(user["id"]))
    cur.execute(f"UPDATE users SET {updates} WHERE id = %s RETURNING *", params)
    fresh = cur.fetchone()
    log_event(cur, user_id=fresh["id"], email=email, event="login_success",
              method="local", request=request)
    conn.commit()
    cur.close()
    return issue_session(conn, fresh, request, response)


@router.post("/auth/refresh")
def refresh(request: Request, response: Response, conn=Depends(get_db)):
    return rotate_session(conn, request, response)


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, conn=Depends(get_db)):
    from app.auth.security import hash_refresh

    raw = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    cur = conn.cursor()
    if raw:
        cur.execute("SELECT family_id, user_id, auth_provider FROM refresh_tokens WHERE token_hash = %s",
                    (hash_refresh(raw),))
        row = cur.fetchone()
        if row:
            cur.execute("UPDATE refresh_tokens SET revoked_at = COALESCE(revoked_at, now()) "
                        "WHERE family_id = %s", (str(row["family_id"]),))
            log_event(cur, user_id=row["user_id"], event="logout", method=row["auth_provider"], request=request)
            conn.commit()
    cur.close()
    clear_refresh_cookie(response)
    return Response(status_code=204, headers=dict(response.headers))


@router.get("/auth/me")
def me(user=Depends(current_user)):
    return user_public(user)


@router.post("/auth/change-password")
def change_password(payload: ChangePasswordIn, request: Request, response: Response,
                    user=Depends(current_user), conn=Depends(get_db)):
    if user["auth_provider"] != "local":
        raise HTTPException(status_code=400, detail="sso_managed_password")
    new = payload.new_password or ""
    if len(new) < 12 or len(new) > 128 or new.lower() == user["email"].lower():
        raise HTTPException(status_code=400, detail="password_not_acceptable")
    if not verify_password(user["password_hash"], payload.current_password or ""):
        raise _invalid_credentials()
    cur = conn.cursor()
    cur.execute("UPDATE users SET password_hash = %s, must_change_password = FALSE, "
                "failed_login_count = 0, locked_until = NULL, updated_at = now() WHERE id = %s RETURNING *",
                (hash_password(new), str(user["id"])))
    fresh = cur.fetchone()
    revoke_all_for_user(conn, user["id"], cur=cur)
    log_event(cur, user_id=user["id"], email=user["email"], event="login_success",
              method="local", request=request, detail="password_changed")
    conn.commit()
    cur.close()
    return issue_session(conn, fresh, request, response)
