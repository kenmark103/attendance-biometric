"""Single-tenant Entra Authorization Code + PKCE login."""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse
from jwt import PyJWKClient

from app.auth.sessions import issue_session, log_event
from app.core import settings
from app.core.db import get_db
from app.core.deps import ROLE_ADMIN, ROLE_VIEWER


router = APIRouter(tags=["auth"])
OIDC_COOKIE = "att_oidc"
OIDC_PATH = "/api/auth"
_jwks: PyJWKClient | None = None


class SsoDenied(Exception):
    def __init__(self, code: str, detail: str | None = None):
        self.code = code
        self.detail = detail


def resolve_role(claims: dict) -> str | None:
    """Resolve only configured Entra app roles/groups; Admin wins."""
    if settings.ENTRA_ROLE_SOURCE == "roles":
        values = claims.get("roles")
        if not isinstance(values, list):
            return None
        if settings.ENTRA_ROLE_ADMIN in values:
            return ROLE_ADMIN
        if settings.ENTRA_ROLE_VIEWER in values:
            return ROLE_VIEWER
        return None

    claim_names = claims.get("_claim_names")
    if isinstance(claim_names, dict) and "groups" in claim_names:
        raise SsoDenied("no_access", "groups_overage")
    values = claims.get("groups")
    if not isinstance(values, list):
        return None
    if settings.ENTRA_GROUP_ADMIN_ID and settings.ENTRA_GROUP_ADMIN_ID in values:
        return ROLE_ADMIN
    if settings.ENTRA_GROUP_VIEWER_ID and settings.ENTRA_GROUP_VIEWER_ID in values:
        return ROLE_VIEWER
    return None


def _jwks_client() -> PyJWKClient:
    global _jwks
    if _jwks is None:
        _jwks = PyJWKClient(settings.config.entra_jwks_url, cache_keys=True, lifespan=3600)
    return _jwks


def validate_entra_id_token(id_token: str, nonce: str) -> dict:
    """Validate only RS256 Entra ID tokens, refreshing an unknown key once."""
    global _jwks
    try:
        key = _jwks_client().get_signing_key_from_jwt(id_token).key
    except Exception:
        _jwks = None
        key = _jwks_client().get_signing_key_from_jwt(id_token).key
    claims = jwt.decode(
        id_token,
        key,
        algorithms=["RS256"],
        audience=settings.ENTRA_CLIENT_ID,
        issuer=settings.config.entra_issuer,
        leeway=settings.ENTRA_CLOCK_SKEW_SECONDS,
        options={"require": ["exp", "iat", "iss", "aud", "oid", "tid", "nonce"]},
    )
    if claims.get("tid") != settings.ENTRA_TENANT_ID:
        raise SsoDenied("login_failed", "wrong_tenant")
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise SsoDenied("login_failed", "bad_nonce")
    email = str(claims.get("preferred_username") or claims.get("email") or "").strip().lower()
    if not email:
        raise SsoDenied("login_failed", "missing_email")
    if settings.ENTRA_ALLOWED_EMAIL_DOMAINS:
        domain = email.rsplit("@", 1)[-1]
        if domain not in settings.ENTRA_ALLOWED_EMAIL_DOMAINS:
            raise SsoDenied("login_failed", "email_domain")
    return claims


def _login_url(code: str) -> str:
    return f"{settings.FRONTEND_URL}/login?{urlencode({'error': code})}"


def _clear_oidc(response: RedirectResponse) -> RedirectResponse:
    kwargs = {"path": OIDC_PATH}
    if settings.COOKIE_DOMAIN:
        kwargs["domain"] = settings.COOKIE_DOMAIN
    response.delete_cookie(OIDC_COOKIE, **kwargs)
    return response


def _fail(code: str) -> RedirectResponse:
    return _clear_oidc(RedirectResponse(_login_url(code), status_code=302))


def resolve_sso_user(conn, claims: dict, role: str):
    email = str(claims.get("preferred_username") or claims.get("email") or "").strip().lower()
    oid, tid = claims["oid"], claims["tid"]
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE entra_oid = %s", (oid,))
    user = cur.fetchone()
    # Deliberately do not silently convert a local account based on email.
    if user is None:
        cur.execute(
            "INSERT INTO users (email, display_name, role, auth_provider, entra_oid, entra_tid) "
            "VALUES (%s,%s,%s,'entra',%s,%s) RETURNING *",
            (email, claims.get("name") or email, role, oid, tid),
        )
        user = cur.fetchone()
    else:
        cur.execute(
            "UPDATE users SET email = %s, display_name = %s, role = %s, entra_tid = %s, "
            "updated_at = now(), last_login_at = now() WHERE id = %s RETURNING *",
            (email, claims.get("name") or email, role, tid, str(user["id"])),
        )
        user = cur.fetchone()
    cur.close()
    if not user["is_active"]:
        raise SsoDenied("inactive")
    return user


@router.get("/auth/entra/login")
def entra_login():
    if not settings.ENTRA_ENABLED:
        raise HTTPException(status_code=404, detail="entra_disabled")
    if not settings.entra_configured():
        raise HTTPException(status_code=503, detail="entra_not_configured")
    state, nonce, verifier = (secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(64))
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    transaction = jwt.encode(
        {"state": state, "nonce": nonce, "verifier": verifier,
         "iat": int(time.time()), "exp": int(time.time()) + 600},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    params = {
        "client_id": settings.ENTRA_CLIENT_ID, "response_type": "code",
        "redirect_uri": settings.ENTRA_REDIRECT_URI, "response_mode": "query",
        "scope": "openid profile email", "state": state, "nonce": nonce,
        "code_challenge": challenge, "code_challenge_method": "S256",
    }
    if settings.ENTRA_PROMPT:
        params["prompt"] = settings.ENTRA_PROMPT
    response = RedirectResponse(f"{settings.config.entra_authority}/oauth2/v2.0/authorize?{urlencode(params)}", 302)
    kwargs = {"httponly": True, "secure": settings.COOKIE_SECURE,
              "samesite": settings.COOKIE_SAMESITE, "path": OIDC_PATH, "max_age": 600}
    if settings.COOKIE_DOMAIN:
        kwargs["domain"] = settings.COOKIE_DOMAIN
    response.set_cookie(OIDC_COOKIE, transaction, **kwargs)
    return response


@router.get("/auth/entra/callback")
async def entra_callback(request: Request, code: str | None = None, state: str | None = None,
                         error: str | None = None, conn=Depends(get_db)):
    if error:
        cur = conn.cursor()
        log_event(cur, event="login_failed", method="entra", request=request, detail="provider_error")
        conn.commit()
        cur.close()
        return _fail("login_failed")
    raw_tx = request.cookies.get(OIDC_COOKIE)
    if not raw_tx or not state or not code:
        return _fail("login_failed")
    try:
        tx = jwt.decode(raw_tx, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        if not secrets.compare_digest(str(state), str(tx.get("state", ""))):
            return _fail("login_failed")
    except jwt.PyJWTError:
        return _fail("login_failed")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            token_response = await client.post(
                f"{settings.config.entra_authority}/oauth2/v2.0/token",
                data={"grant_type": "authorization_code", "client_id": settings.ENTRA_CLIENT_ID,
                      "client_secret": settings.ENTRA_CLIENT_SECRET, "code": code,
                      "redirect_uri": settings.ENTRA_REDIRECT_URI, "code_verifier": tx["verifier"]},
            )
        if token_response.status_code != 200:
            return _fail("login_failed")
        id_token = token_response.json().get("id_token")
        if not id_token:
            return _fail("login_failed")
        claims = await run_in_threadpool(validate_entra_id_token, id_token, tx["nonce"])
        role = resolve_role(claims)
        if role is None:
            raise SsoDenied("no_access")
        user = resolve_sso_user(conn, claims, role)
    except SsoDenied as denied:
        cur = conn.cursor()
        event = "login_denied_inactive" if denied.code == "inactive" else "login_denied_no_role"
        log_event(cur, event=event, method="entra", email=(claims.get("preferred_username") if "claims" in locals() else None),
                  entra_oid=(claims.get("oid") if "claims" in locals() else None), request=request, detail=denied.detail)
        conn.commit()
        cur.close()
        return _fail(denied.code)
    except Exception:
        return _fail("login_failed")

    response = _clear_oidc(RedirectResponse(f"{settings.FRONTEND_URL}/", status_code=302))
    body = issue_session(conn, user, request, response)
    del body  # tokens are never placed in the redirect response.
    cur = conn.cursor()
    log_event(cur, user_id=user["id"], email=user["email"], event="login_success", method="entra",
              entra_oid=user.get("entra_oid"), request=request)
    conn.commit()
    cur.close()
    return response
