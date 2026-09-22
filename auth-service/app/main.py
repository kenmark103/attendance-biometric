"""
Auth service — OIDC login, provider-agnostic by design.

Google is wired up now so you can learn/test the OAuth2/OIDC flow end to
end. Entra ID (Technobrain's tenant) is config-driven and will activate
the moment ENTRA_TENANT_ID / ENTRA_CLIENT_ID / ENTRA_CLIENT_SECRET are set
— no code change needed, per what the senior dev expected.

Authorization (who's allowed in, what role) is deliberately NOT tied to
which provider authenticated them — see app_users table. Swapping the
provider later doesn't touch the whitelist.
"""
import os
import time
from typing import Optional

import jwt
from authlib.integrations.starlette_client import OAuth
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import RedirectResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware
import psycopg2
import psycopg2.extras

AUTH_SECRET = os.environ["AUTH_SECRET"]  # shared with api service to verify issued tokens
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://attendance:attendance@db:5432/attendance"
)
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3001")

app = FastAPI(title="Attendance Auth Service")
app.add_middleware(SessionMiddleware, secret_key=AUTH_SECRET)

oauth = OAuth()

# --- Google: real, for learning/testing the flow -----------------------
if os.environ.get("GOOGLE_CLIENT_ID"):
    oauth.register(
        name="google",
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

# --- Entra ID: config-ready, inactive until these env vars are set -----
# This is the "small change" the senior dev expects: same OAuth client
# shape as Google, just a different discovery URL and credentials.
ENTRA_TENANT_ID = os.environ.get("ENTRA_TENANT_ID")
if ENTRA_TENANT_ID and os.environ.get("ENTRA_CLIENT_ID"):
    oauth.register(
        name="entra",
        client_id=os.environ["ENTRA_CLIENT_ID"],
        client_secret=os.environ["ENTRA_CLIENT_SECRET"],
        server_metadata_url=f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}/v2.0/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

CONFIGURED_PROVIDERS = [p for p in ("google", "entra") if p in oauth._clients]


def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def issue_session_token(email: str, name: str, role: str, employee_id: Optional[str]) -> str:
    payload = {
        "email": email,
        "name": name,
        "role": role,
        "employee_id": employee_id,
        "iat": int(time.time()),
        "exp": int(time.time()) + 60 * 60 * 8,  # 8h session
    }
    return jwt.encode(payload, AUTH_SECRET, algorithm="HS256")


@app.get("/auth/providers")
def list_providers():
    """So the frontend knows which login buttons to actually show."""
    return {"configured": CONFIGURED_PROVIDERS}


@app.get("/auth/login/{provider}")
async def login(provider: str, request: Request):
    if provider not in CONFIGURED_PROVIDERS:
        raise HTTPException(
            status_code=501,
            detail=f"Provider '{provider}' is not configured yet. "
                   f"Set the {provider.upper()}_CLIENT_ID / _SECRET env vars to enable it.",
        )
    client = oauth.create_client(provider)
    redirect_uri = request.url_for("auth_callback", provider=provider)
    return await client.authorize_redirect(request, redirect_uri)


@app.get("/auth/callback/{provider}", name="auth_callback")
async def auth_callback(provider: str, request: Request):
    if provider not in CONFIGURED_PROVIDERS:
        raise HTTPException(status_code=501, detail=f"Provider '{provider}' is not configured.")

    client = oauth.create_client(provider)
    token = await client.authorize_access_token(request)
    userinfo = token.get("userinfo") or await client.userinfo(token=token)

    email = userinfo["email"]
    name = userinfo.get("name", email)
    provider_user_id = userinfo.get("sub")

    # Look up (not create) — this app is invite-only by design. Someone
    # logging in with a valid Google/Entra account but no app_users row
    # is authenticated but NOT authorized, and gets a clear 403.
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, role, employee_id FROM app_users WHERE email = %s", (email,))
    row = cur.fetchone()

    if row is None:
        cur.close()
        conn.close()
        raise HTTPException(
            status_code=403,
            detail=f"{email} authenticated successfully but isn't on the app's access list yet. "
                   f"Ask an admin to add you to app_users.",
        )

    cur.execute(
        "UPDATE app_users SET provider = %s, provider_user_id = %s, last_login_at = now() WHERE id = %s",
        (provider, provider_user_id, row["id"]),
    )
    conn.commit()
    cur.close()
    conn.close()

    session_token = issue_session_token(email, name, row["role"], row["employee_id"])

    # Redirect back to the frontend with the token. A cookie is arguably
    # cleaner than a URL param long-term — fine for local dev, revisit
    # before this touches anything real.
    return RedirectResponse(f"{FRONTEND_URL}?token={session_token}")


@app.get("/auth/me")
def whoami(request: Request):
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = auth_header.removeprefix("Bearer ")
    try:
        payload = jwt.decode(token, AUTH_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")
    return JSONResponse(payload)
