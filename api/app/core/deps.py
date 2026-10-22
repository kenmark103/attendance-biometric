"""Deny-by-default authorization dependencies."""
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer

from app.auth.security import decode_access_token
from app.core import settings
from app.core.db import get_db


ROLE_VIEWER = "Viewer"
ROLE_ADMIN = "Admin"
bearer = HTTPBearer(auto_error=False)


def current_user(creds=Depends(bearer), conn=Depends(get_db)):
    if not creds:
        raise HTTPException(401, "not_authenticated", headers={"WWW-Authenticate": "Bearer"})
    try:
        claims = decode_access_token(creds.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "token_expired", headers={"WWW-Authenticate": "Bearer"})
    except jwt.PyJWTError:
        raise HTTPException(401, "invalid_token", headers={"WWW-Authenticate": "Bearer"})
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = %s", (claims["sub"],))
    user = cur.fetchone()
    cur.close()
    if not user or not user["is_active"]:
        raise HTTPException(401, "invalid_token")
    return user


def require_viewer(user=Depends(current_user)):
    if user.get("must_change_password"):
        raise HTTPException(403, "password_change_required")
    if user["role"] not in {ROLE_VIEWER, ROLE_ADMIN}:
        raise HTTPException(403, "forbidden")
    return user


def require_admin(user=Depends(current_user)):
    if user.get("must_change_password"):
        raise HTTPException(403, "password_change_required")
    if user["role"] != ROLE_ADMIN:
        raise HTTPException(403, "forbidden")
    return user


# Temporary aliases keep existing routers concise while preserving exactly two
# authorization levels. AUTH_REQUIRED=false remains a deliberate dev escape.
if settings.AUTH_REQUIRED:
    viewer = require_viewer
    admin = require_admin
else:
    def viewer():
        return {"id": None, "email": "dev@local", "role": ROLE_ADMIN, "employee_id": None}

    def admin():
        return {"id": None, "email": "dev@local", "role": ROLE_ADMIN, "employee_id": None}
