"""Refresh-token sessions. Same psycopg2 style as the rest of the api.

Cookie path note: the browser talks to the API through the nginx `/api/`
prefix, so a cookie with path `/auth` would never be sent back (cookie path
must prefix the request path, and the browser sees `/api/auth/...`). Path
`/` keeps the cookie working both through the proxy and if the frontend is
ever served from the API origin.
"""
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, Response

from app.auth.security import create_access_token, hash_refresh, new_refresh_token
from app.core import settings

REFRESH_COOKIE = "refresh_token"
REUSE_GRACE_SECONDS = 10


def _now():
    return datetime.now(timezone.utc)


def _ip(request: Request | None) -> str | None:
    try:
        return request.client.host if request and request.client else None
    except Exception:
        return None


def _ua(request: Request | None) -> str | None:
    try:
        return request.headers.get("user-agent") if request else None
    except Exception:
        return None


def log_event(cur, *, user_id, email, event, provider=None, request=None, detail=None):
    cur.execute(
        "INSERT INTO auth_events (user_id, email, event, provider, ip, user_agent, detail)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (str(user_id) if user_id else None, email, event, provider,
         _ip(request), _ua(request), detail),
    )


def user_public(user) -> dict:
    return {
        "id": str(user["id"]),
        "email": user["email"],
        "display_name": user.get("display_name"),
        "role": user["role"],
        "provider": user["auth_provider"],
        "must_change_password": bool(user["must_change_password"]),
    }


def set_refresh_cookie(response: Response, raw: str, max_age: int):
    response.set_cookie(
        REFRESH_COOKIE, raw,
        httponly=True, secure=settings.COOKIE_SECURE, samesite="lax",
        path="/", max_age=max_age,
    )


def clear_refresh_cookie(response: Response):
    response.set_cookie(
        REFRESH_COOKIE, "",
        httponly=True, secure=settings.COOKIE_SECURE, samesite="lax",
        path="/", max_age=0,
    )


def _expiry_seconds(expires_at) -> int:
    delta = (expires_at - _now()).total_seconds()
    return max(1, int(delta))


def issue_session(conn, user, request: Request | None, response: Response) -> dict:
    """Brand-new login: fresh family, set cookie, return token body."""
    now = _now()
    family_id = str(uuid.uuid4())
    family_expires_at = now + timedelta(days=settings.REFRESH_ABSOLUTE_DAYS)
    expires_at = now + timedelta(days=settings.REFRESH_TTL_DAYS)
    raw, token_hash = new_refresh_token()

    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO refresh_tokens (user_id, family_id, token_hash, expires_at,"
            " family_expires_at, user_agent, ip) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (str(user["id"]), family_id, token_hash, expires_at,
             family_expires_at, _ua(request), _ip(request)),
        )
        cur.execute(
            "UPDATE users SET last_login_at = %s, updated_at = %s WHERE id = %s",
            (now, now, str(user["id"])),
        )
        cur.execute(
            "DELETE FROM refresh_tokens WHERE family_expires_at < %s",
            (now - timedelta(days=1),),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()

    # Re-read so the body reflects the just-written row.
    from app.core.db import get_conn as _get_conn
    conn2 = _get_conn()
    try:
        cur2 = conn2.cursor()
        cur2.execute("SELECT * FROM users WHERE id = %s", (str(user["id"]),))
        fresh = cur2.fetchone()
        cur2.close()
    finally:
        conn2.close()

    access, ttl = create_access_token(fresh or user)
    set_refresh_cookie(response, raw, _expiry_seconds(expires_at))
    return {
        "access_token": access, "token_type": "bearer", "expires_in": ttl,
        "user": user_public(fresh or user),
    }


def rotate_session(conn, request: Request, response: Response) -> dict:
    """POST /auth/refresh. Reuse-vs-race rules, all in one transaction."""
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise HTTPException(status_code=401, detail="invalid_refresh")

    now = _now()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT * FROM refresh_tokens WHERE token_hash = %s FOR UPDATE",
            (hash_refresh(raw),),
        )
        row = cur.fetchone()
        if row is None:
            conn.rollback()
            raise HTTPException(status_code=401, detail="invalid_refresh")

        if row["revoked_at"] is not None:
            # Reuse vs. race: two tabs rotating within the grace window is
            # benign; replaying an old token later is theft.
            age = (now - row["revoked_at"]).total_seconds()
            if row["replaced_by"] is not None and age > REUSE_GRACE_SECONDS:
                cur.execute(
                    "UPDATE refresh_tokens SET revoked_at = %s WHERE family_id = %s"
                    " AND revoked_at IS NULL",
                    (now, str(row["family_id"])),
                )
                log_event(cur, user_id=row["user_id"], email=None,
                          event="refresh_reuse", request=request,
                          detail=f"family={row['family_id']}")
                conn.commit()
            else:
                conn.rollback()
            raise HTTPException(status_code=401, detail="invalid_refresh")

        if now > row["expires_at"] or now > row["family_expires_at"]:
            conn.rollback()
            raise HTTPException(status_code=401, detail="invalid_refresh")

        cur.execute("SELECT * FROM users WHERE id = %s", (str(row["user_id"]),))
        user = cur.fetchone()
        if user is None or not user["is_active"]:
            cur.execute(
                "UPDATE refresh_tokens SET revoked_at = %s WHERE family_id = %s"
                " AND revoked_at IS NULL",
                (now, str(row["family_id"])),
            )
            conn.commit()
            raise HTTPException(status_code=401, detail="invalid_refresh")

        new_expires = min(now + timedelta(days=settings.REFRESH_TTL_DAYS),
                          row["family_expires_at"])
        new_raw, new_hash = new_refresh_token()
        new_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO refresh_tokens (id, user_id, family_id, token_hash, expires_at,"
            " family_expires_at, user_agent, ip) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (new_id, str(user["id"]), str(row["family_id"]), new_hash,
             new_expires, row["family_expires_at"], _ua(request), _ip(request)),
        )
        cur.execute(
            "UPDATE refresh_tokens SET revoked_at = %s, replaced_by = %s WHERE id = %s",
            (now, new_id, str(row["id"])),
        )
        cur.execute(
            "UPDATE users SET updated_at = %s WHERE id = %s", (now, str(user["id"]))
        )
        conn.commit()
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()

    access, ttl = create_access_token(user)
    set_refresh_cookie(response, new_raw, _expiry_seconds(new_expires))
    return {
        "access_token": access, "token_type": "bearer", "expires_in": ttl,
        "user": user_public(user),
    }


def revoke_family(conn, family_id) -> None:
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE refresh_tokens SET revoked_at = now() WHERE family_id = %s"
            " AND revoked_at IS NULL",
            (str(family_id),),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def revoke_all_for_user(conn, user_id) -> None:
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE refresh_tokens SET revoked_at = now() WHERE user_id = %s"
            " AND revoked_at IS NULL",
            (str(user_id),),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
