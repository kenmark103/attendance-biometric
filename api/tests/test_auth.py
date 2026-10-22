"""Database-backed authentication checks for the Viewer/Admin contract.

Run in the API container after migration 010 has been applied.
"""
import os
import uuid
from http.cookies import SimpleCookie

os.environ.setdefault("JWT_SECRET", "test-secret-0123456789abcdef-test-secret")
os.environ.setdefault("DATABASE_URL", "postgresql://attendance:attendance@localhost:5434/attendance")

import pytest
from fastapi.testclient import TestClient

from app.auth.security import hash_password, hash_refresh
from app.core.db import get_conn
from app.main import app

pytestmark = pytest.mark.db
client = TestClient(app, follow_redirects=False)


def _email(tag):
    return f"zt-{tag}-{uuid.uuid4().hex[:8]}@attendance.internal"


def _user(email, role="Viewer", active=True):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("INSERT INTO users (email, display_name, role, auth_provider, password_hash, is_active) VALUES (%s,%s,%s,'local',%s,%s) RETURNING id", (email, email, role, hash_password("0123456789abcdef"), active))
    uid = str(cur.fetchone()["id"]); conn.commit(); cur.close(); conn.close(); return uid


@pytest.fixture(autouse=True)
def cleanup():
    yield
    conn = get_conn(); cur = conn.cursor()
    cur.execute("DELETE FROM wfh_recalls WHERE created_by IN (SELECT id FROM users WHERE email LIKE 'zt-%%')")
    cur.execute("DELETE FROM wfh_policies WHERE created_by IN (SELECT id FROM users WHERE email LIKE 'zt-%%')")
    cur.execute("DELETE FROM audit_log WHERE actor_user_id IN (SELECT id FROM users WHERE email LIKE 'zt-%%')")
    cur.execute("DELETE FROM auth_events WHERE email LIKE 'zt-%%'")
    cur.execute("DELETE FROM refresh_tokens WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'zt-%%')")
    cur.execute("DELETE FROM users WHERE email LIKE 'zt-%%'")
    conn.commit(); cur.close(); conn.close()


def login(email):
    response = client.post("/auth/login", json={"email": email, "password": "0123456789abcdef"})
    assert response.status_code == 200, response.text
    return response


def test_login_issues_short_app_token_and_config_hides_secrets():
    email = _email("login"); _user(email)
    response = login(email)
    assert response.json()["user"]["role"] == "Viewer"
    assert 0 < response.json()["expires_in"] <= 3600
    assert "att_refresh=" in response.headers["set-cookie"]
    config = client.get("/auth/config").json()
    assert set(config) == {"entra_enabled", "local_auth_enabled", "idle_logout_minutes", "idle_warning_seconds", "support_contact_text"}


def test_viewer_is_read_only_and_admin_can_manage_users():
    viewer_email, admin_email = _email("viewer"), _email("admin")
    _user(viewer_email); _user(admin_email, "Admin")
    viewer_token = login(viewer_email).json()["access_token"]
    admin_token = login(admin_email).json()["access_token"]
    assert client.get("/teams", headers={"Authorization": f"Bearer {viewer_token}"}).status_code == 200
    assert client.get("/admin/users", headers={"Authorization": f"Bearer {viewer_token}"}).status_code == 403
    assert client.get("/admin/users", headers={"Authorization": f"Bearer {admin_token}"}).status_code == 200


def test_refresh_rotates_and_replay_outside_grace_revokes_family():
    email = _email("refresh"); _user(email)
    session = TestClient(app, follow_redirects=False)
    assert session.post("/auth/login", json={"email": email, "password": "0123456789abcdef"}).status_code == 200
    old = session.cookies.get("att_refresh")
    refreshed = session.post("/auth/refresh", cookies={"att_refresh": old})
    assert refreshed.status_code == 200
    jar = SimpleCookie(); jar.load(refreshed.headers["set-cookie"])
    fresh = jar["att_refresh"].value
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE refresh_tokens SET revoked_at = now() - interval '30 seconds' WHERE token_hash=%s", (hash_refresh(old),)); conn.commit(); cur.close(); conn.close()
    assert session.post("/auth/refresh", cookies={"att_refresh": old}).status_code == 401
    assert session.post("/auth/refresh", cookies={"att_refresh": fresh}).status_code == 401
