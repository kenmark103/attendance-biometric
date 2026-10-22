"""Application session families: opaque refresh cookies and short JWTs."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, Response

from app.auth.security import create_access_token, hash_refresh, new_refresh_token
from app.core import settings


REFRESH_COOKIE_PATH = "/api/auth"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ip(request: Request | None) -> str | None:
    return request.client.host if request and request.client else None


def _ua(request: Request | None) -> str | None:
    return request.headers.get("user-agent") if request else None


def log_event(cur, *, user_id=None, email=None, event: str, method=None,
              entra_oid=None, request: Request | None = None, detail=None) -> None:
    """Persist metadata-only auth events; never pass secrets to this helper."""
    cur.execute(
        "INSERT INTO auth_events (user_id, email, event, method, entra_oid, ip, user_agent, detail) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (str(user_id) if user_id else None, email, event, method, entra_oid,
         _ip(request), _ua(request), detail),
    )


def user_public(user) -> dict:
    return {
        "id": str(user["id"]),
        "email": user["email"],
        "display_name": user.get("display_name"),
        "role": user["role"],
        "auth_provider": user["auth_provider"],
        "must_change_password": bool(user.get("must_change_password")),
    }


def set_refresh_cookie(response: Response, raw: str, max_age: int) -> None:
    kwargs = {
        "httponly": True,
        "secure": settings.COOKIE_SECURE,
        "samesite": settings.COOKIE_SAMESITE,
        "path": REFRESH_COOKIE_PATH,
        "max_age": max(1, max_age),
    }
    if settings.COOKIE_DOMAIN:
        kwargs["domain"] = settings.COOKIE_DOMAIN
    response.set_cookie(settings.REFRESH_COOKIE_NAME, raw, **kwargs)


def clear_refresh_cookie(response: Response) -> None:
    kwargs = {"path": REFRESH_COOKIE_PATH}
    if settings.COOKIE_DOMAIN:
        kwargs["domain"] = settings.COOKIE_DOMAIN
    response.delete_cookie(settings.REFRESH_COOKIE_NAME, **kwargs)


def _expiry_seconds(expires_at: datetime) -> int:
    return max(1, int((expires_at - _now()).total_seconds()))


def _family_cap(now: datetime, provider: str) -> datetime:
    days = settings.REFRESH_ABSOLUTE_TTL_DAYS
    if provider == "entra":
        days = min(days, settings.ENTRA_REAUTH_DAYS)
    return now + timedelta(days=days)


def _session_body(user) -> dict:
    access, ttl = create_access_token(user)
    return {"access_token": access, "token_type": "bearer", "expires_in": ttl,
            "user": user_public(user)}


def issue_session(conn, user, request: Request | None, response: Response) -> dict:
    """Start a family at login; no provider token is ever retained."""
    now = _now()
    family_id = str(uuid.uuid4())
    family_started_at = now
    family_cap = _family_cap(now, user["auth_provider"])
    expires_at = min(now + timedelta(days=settings.REFRESH_IDLE_TTL_DAYS), family_cap)
    raw, token_hash = new_refresh_token()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO refresh_tokens (user_id, family_id, token_hash, family_started_at, "
            "auth_provider, expires_at, last_used_at, created_at, user_agent, ip) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (str(user["id"]), family_id, token_hash, family_started_at,
             user["auth_provider"], expires_at, now, now, _ua(request), _ip(request)),
        )
        cur.execute(
            "UPDATE users SET last_login_at = %s, updated_at = %s WHERE id = %s RETURNING *",
            (now, now, str(user["id"])),
        )
        fresh = cur.fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
    set_refresh_cookie(response, raw, _expiry_seconds(expires_at))
    return _session_body(fresh)


def _expired(response: Response) -> None:
    clear_refresh_cookie(response)
    raise HTTPException(status_code=401, detail="session_expired")


def rotate_session(conn, request: Request, response: Response) -> dict:
    """Rotate one family, with a short benign-race grace window."""
    raw = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    if not raw:
        _expired(response)
    now = _now()
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM refresh_tokens WHERE token_hash = %s FOR UPDATE", (hash_refresh(raw),))
        row = cur.fetchone()
        if row is None:
            conn.rollback()
            _expired(response)

        cur.execute("SELECT * FROM users WHERE id = %s FOR UPDATE", (str(row["user_id"]),))
        user = cur.fetchone()
        if user is None or not user["is_active"]:
            cur.execute("UPDATE refresh_tokens SET revoked_at = %s WHERE family_id = %s AND revoked_at IS NULL",
                        (now, str(row["family_id"])))
            conn.commit()
            _expired(response)

        family_cap = _family_cap(row["family_started_at"], row["auth_provider"])
        if now >= row["expires_at"] or now >= family_cap:
            cur.execute("UPDATE refresh_tokens SET revoked_at = %s WHERE family_id = %s AND revoked_at IS NULL",
                        (now, str(row["family_id"])))
            conn.commit()
            _expired(response)

        if row["revoked_at"] is not None:
            grace = (now - row["revoked_at"]).total_seconds()
            replacement_ok = False
            if row["replaced_by"] is not None and grace <= settings.REFRESH_REUSE_GRACE_SECONDS:
                cur.execute("SELECT revoked_at, expires_at FROM refresh_tokens WHERE id = %s", (str(row["replaced_by"]),))
                replacement = cur.fetchone()
                replacement_ok = bool(replacement and replacement["revoked_at"] is None
                                      and replacement["expires_at"] > now)
            if replacement_ok:
                log_event(cur, user_id=user["id"], email=user["email"], event="token_refresh",
                          method=row["auth_provider"], request=request, detail="grace")
                conn.commit()
                return _session_body(user)
            cur.execute("UPDATE refresh_tokens SET revoked_at = %s WHERE family_id = %s AND revoked_at IS NULL",
                        (now, str(row["family_id"])))
            log_event(cur, user_id=user["id"], email=user["email"],
                      event="refresh_reuse_detected", method=row["auth_provider"], request=request)
            conn.commit()
            _expired(response)

        new_expires = min(now + timedelta(days=settings.REFRESH_IDLE_TTL_DAYS), family_cap)
        new_raw, new_hash = new_refresh_token()
        new_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO refresh_tokens (id, user_id, family_id, token_hash, family_started_at, "
            "auth_provider, expires_at, last_used_at, created_at, user_agent, ip) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (new_id, str(user["id"]), str(row["family_id"]), new_hash,
             row["family_started_at"], row["auth_provider"], new_expires,
             now, now, _ua(request), _ip(request)),
        )
        cur.execute("UPDATE refresh_tokens SET revoked_at = %s, replaced_by = %s, last_used_at = %s WHERE id = %s",
                    (now, new_id, now, str(row["id"])))
        cur.execute("UPDATE users SET updated_at = %s WHERE id = %s", (now, str(user["id"])))
        log_event(cur, user_id=user["id"], email=user["email"], event="token_refresh",
                  method=row["auth_provider"], request=request)
        conn.commit()
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
    set_refresh_cookie(response, new_raw, _expiry_seconds(new_expires))
    return _session_body(user)


def revoke_family(conn, family_id, *, cur=None, now=None) -> None:
    own_cursor = cur is None
    cur = cur or conn.cursor()
    try:
        cur.execute("UPDATE refresh_tokens SET revoked_at = COALESCE(revoked_at, %s) "
                    "WHERE family_id = %s", (now or _now(), str(family_id)))
        if own_cursor:
            conn.commit()
    except Exception:
        if own_cursor:
            conn.rollback()
        raise
    finally:
        if own_cursor:
            cur.close()


def revoke_all_for_user(conn, user_id, *, cur=None) -> None:
    own_cursor = cur is None
    cur = cur or conn.cursor()
    try:
        cur.execute("UPDATE refresh_tokens SET revoked_at = COALESCE(revoked_at, now()) "
                    "WHERE user_id = %s", (str(user_id),))
        if own_cursor:
            conn.commit()
    except Exception:
        if own_cursor:
            conn.rollback()
        raise
    finally:
        if own_cursor:
            cur.close()
