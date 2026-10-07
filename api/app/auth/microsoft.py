"""Microsoft Entra SSO routes (/auth/microsoft). Inactive (503) until the
ENTRA_* env vars are set — email/password keeps working meanwhile."""
import base64
import hashlib
import secrets
import time
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse
from jwt import PyJWKClient

from app.auth.sessions import issue_session, log_event
from app.core import settings
from app.core.db import get_conn
from app.core.deps import RANK

router = APIRouter(tags=["auth"])
OIDC_COOKIE = "oidc_tx"


class SsoDenied(Exception):
    def __init__(self, code: str):
        self.code = code


def pick_role(roles):
    valid = [r.lower() for r in (roles or []) if r.lower() in RANK]
    return max(valid, key=lambda r: RANK[r]) if valid else None


_jwks = None


def _jwks_client() -> PyJWKClient:
    global _jwks
    if _jwks is None:
        _jwks = PyJWKClient(
            f'https://login.microsoftonline.com/{settings.ENTRA_TENANT_ID}/discovery/v2.0/keys',
            cache_keys=True, lifespan=3600,
        )
    return _jwks


def validate_entra_id_token(id_token: str, nonce: str) -> dict:
    key = _jwks_client().get_signing_key_from_jwt(id_token).key
    claims = jwt.decode(
        id_token, key, algorithms=['RS256'],
        audience=settings.ENTRA_CLIENT_ID,
        issuer=f'https://login.microsoftonline.com/{settings.ENTRA_TENANT_ID}/v2.0',
        options={'require': ['exp', 'iat', 'iss', 'aud', 'oid', 'tid']},
    )
    if claims['tid'] != settings.ENTRA_TENANT_ID:
        raise ValueError('wrong_tenant')
    if not secrets.compare_digest(str(claims.get('nonce', '')), nonce):
        raise ValueError('bad_nonce')
    return claims


def _fail(code: str) -> RedirectResponse:
    return RedirectResponse(f'/?auth_error={code}', status_code=302)


def resolve_sso_user(conn, claims):
    email = (claims.get('email') or claims.get('preferred_username') or '').strip().lower()
    oid, tid = claims['oid'], claims['tid']
    entra_role = pick_role(claims.get('roles'))

    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE entra_oid = %s", (oid,))
    user = cur.fetchone()
    if not user and email:
        cur.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cur.fetchone()
        if user and user['auth_provider'] != 'entra':
            cur.close()
            raise SsoDenied('local_account_exists')  # never merge into a local account

    if not user:
        if not entra_role:
            cur.close()
            raise SsoDenied('access_not_granted')
        cur.execute(
            "INSERT INTO users (email, display_name, role, auth_provider, entra_oid, entra_tid)"
            " VALUES (%s,%s,%s,'entra',%s,%s) RETURNING *",
            (email, claims.get('name') or email, entra_role, oid, tid),
        )
        user = cur.fetchone()
    else:
        if not user['entra_oid']:
            cur.execute(
                "UPDATE users SET entra_oid = %s, entra_tid = %s, updated_at = now()"
                " WHERE id = %s",
                (oid, tid, str(user['id'])),
            )
        if claims.get('name'):
            cur.execute(
                "UPDATE users SET display_name = %s, updated_at = now() WHERE id = %s",
                (claims['name'], str(user['id'])),
            )
        if entra_role:
            # Entra is the source of truth when it supplies a role.
            cur.execute(
                "UPDATE users SET role = %s, updated_at = now() WHERE id = %s",
                (entra_role, str(user['id'])),
            )
        cur.execute("SELECT * FROM users WHERE id = %s", (str(user['id']),))
        user = cur.fetchone()
    cur.close()
    # An explicit disable beats an Entra role.
    if not user['is_active']:
        raise SsoDenied('account_disabled')
    return user


@router.get("/auth/microsoft/login")
def ms_login():
    if not settings.entra_configured():
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="sso_not_configured")
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b'=').decode()

    tx = jwt.encode(
        {'state': state, 'nonce': nonce, 'verifier': verifier,
         'iat': int(time.time()), 'exp': int(time.time()) + 600},
        settings.JWT_SECRET, algorithm='HS256',
    )
    params = {
        'client_id': settings.ENTRA_CLIENT_ID,
        'response_type': 'code',
        'redirect_uri': settings.ENTRA_REDIRECT_URI,
        'response_mode': 'query',
        'scope': 'openid profile email',
        'state': state, 'nonce': nonce,
        'code_challenge': challenge, 'code_challenge_method': 'S256',
    }
    url = (f'https://login.microsoftonline.com/{settings.ENTRA_TENANT_ID}'
           f'/oauth2/v2.0/authorize?{urlencode(params)}')
    resp = RedirectResponse(url, status_code=302)
    # Lax (not Strict): Strict would not be sent on the redirect back from
    # Microsoft. Path `/` — the browser reaches us via the `/api/` proxy
    # prefix, so `/auth/microsoft` would never match (see sessions.py note).
    resp.set_cookie(OIDC_COOKIE, tx, httponly=True,
                    secure=settings.COOKIE_SECURE, samesite='lax', path='/',
                    max_age=600)
    return resp


@router.get("/auth/microsoft/callback")
async def ms_callback(request: Request, code: str | None = None,
                      state: str | None = None, error: str | None = None):
    if error:
        return _fail('sso_failed')
    raw_tx = request.cookies.get(OIDC_COOKIE)

    def _clear(resp):
        resp.delete_cookie(OIDC_COOKIE, path='/')
        return resp

    if not raw_tx:
        return _clear(_fail('sso_failed'))
    try:
        tx = jwt.decode(raw_tx, settings.JWT_SECRET, algorithms=['HS256'])
    except jwt.PyJWTError:
        return _clear(_fail('sso_failed'))
    if not state or not secrets.compare_digest(str(state), str(tx.get('state', ''))):
        return _clear(_fail('sso_failed'))
    if not code:
        return _clear(_fail('sso_failed'))

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            token_resp = await client.post(
                f'https://login.microsoftonline.com/{settings.ENTRA_TENANT_ID}/oauth2/v2.0/token',
                data={'grant_type': 'authorization_code',
                      'client_id': settings.ENTRA_CLIENT_ID,
                      'client_secret': settings.ENTRA_CLIENT_SECRET,
                      'code': code,
                      'redirect_uri': settings.ENTRA_REDIRECT_URI,
                      'code_verifier': tx['verifier']},
            )
    except httpx.HTTPError:
        return _clear(_fail('sso_failed'))
    if token_resp.status_code != 200:
        return _clear(_fail('sso_failed'))
    id_token = token_resp.json().get('id_token')
    if not id_token:
        return _clear(_fail('sso_failed'))

    try:
        # PyJWKClient does blocking IO on a cache miss — keep it off the loop.
        claims = await run_in_threadpool(
            validate_entra_id_token, id_token, tx['nonce'])
    except Exception:
        return _clear(_fail('sso_failed'))

    conn = get_conn()
    try:
        try:
            user = resolve_sso_user(conn, claims)
        except SsoDenied as denied:
            cur = conn.cursor()
            log_event(cur, user_id=None,
                      email=(claims.get('email') or claims.get('preferred_username') or ''),
                      event='sso_denied', provider='entra', request=request,
                      detail=denied.code)
            conn.commit()
            cur.close()
            return _clear(_fail(denied.code))
        resp = _clear(RedirectResponse('/', status_code=302))
        issue_session(conn, user, request, resp)
        cur = conn.cursor()
        log_event(cur, user_id=user['id'], email=user['email'],
                  event='sso_ok', provider='entra', request=request)
        conn.commit()
        cur.close()
        return resp
    finally:
        conn.close()
