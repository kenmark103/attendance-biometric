"""Per-request auth. Sync psycopg2 style, matching the rest of the api.

- `current_user` re-reads the users row on EVERY request, so deactivation
  and role changes apply immediately.
- The JWT `role` claim is informational for the frontend only; the server
  authorizes from the DB row.
"""
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer

from app.auth.security import decode_access_token
from app.core import settings
from app.core.db import get_conn

bearer = HTTPBearer(auto_error=False)
RANK = {'viewer': 1, 'manager': 2, 'admin': 3}


def current_user(creds=Depends(bearer)):
    if not creds:
        raise HTTPException(401, 'not_authenticated',
                            headers={'WWW-Authenticate': 'Bearer'})
    try:
        claims = decode_access_token(creds.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, 'token_expired',
                            headers={'WWW-Authenticate': 'Bearer'})
    except jwt.PyJWTError:
        raise HTTPException(401, 'invalid_token',
                            headers={'WWW-Authenticate': 'Bearer'})
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE id = %s", (claims['sub'],))
        user = cur.fetchone()
        cur.close()
    finally:
        conn.close()
    if not user or not user['is_active']:
        raise HTTPException(401, 'invalid_token')
    return user


def require_role(minimum: str):
    def checker(user=Depends(current_user)):
        if user['must_change_password']:
            raise HTTPException(403, 'password_change_required')
        if RANK.get(user['role'], 0) < RANK[minimum]:
            raise HTTPException(403, 'forbidden')
        return user
    return checker


def require_admin(user=Depends(current_user)):
    """Bulk-ingestion choke point: admin/service accounts only."""
    if user['must_change_password']:
        raise HTTPException(403, 'password_change_required')
    if user['role'] != 'admin':
        raise HTTPException(
            status_code=403, detail='Only admin/service accounts may write attendance data')
    return user


# Import-time role aliases. When AUTH_REQUIRED=false (open dev), everything
# resolves to a stub admin so no tokens are needed.
if settings.AUTH_REQUIRED:
    admin = require_admin
    viewer = require_role("viewer")
    manager = require_role("manager")
else:
    def viewer():
        return {"email": "dev@local", "role": "admin", "employee_id": None}

    def manager():
        return {"email": "dev@local", "role": "admin", "employee_id": None}

    def admin():
        return {"email": "dev@local", "role": "admin", "employee_id": None}
