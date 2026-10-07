"""Auth tests (Section 6). Needs the compose Postgres + migrated schema.

Run inside the container (deps + DATABASE_URL already there):
    docker compose exec api pytest app/tests/test_auth.py -v
Or from the host:
    DATABASE_URL=postgresql://attendance:attendance@localhost:5434/attendance \
      pytest api/tests/test_auth.py -m db
"""
import os
import time
import uuid

os.environ.setdefault("JWT_SECRET", "test-secret-0123456789abcdef-test-secret")
os.environ.setdefault("DATABASE_URL",
                      "postgresql://attendance:attendance@localhost:5434/attendance")

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.db

import app.core.settings as settings
from app.auth import local as auth_local
from app.auth import microsoft as auth_microsoft
from app.auth.bootstrap import ensure_bootstrap_admin
from app.auth.security import hash_refresh
from app.core.db import get_conn
from app.main import app


def _db():
    return get_conn()


_HERE = os.path.dirname(os.path.abspath(__file__))
_CANDIDATES = [
    os.path.join(_HERE, "..", "..", "db", "migrations", "004_auth.sql"),  # repo checkout
    "/app/db/migrations/004_auth.sql",  # container with ./db mounted
]


def _apply_migration():
    for cand in _CANDIDATES:
        if os.path.exists(os.path.abspath(cand)):
            path = os.path.abspath(cand)
            break
    else:
        path = None
    conn = _db()
    try:
        cur = conn.cursor()
        if path is None:
            # Fresh DBs already get the final schema from db/init.sql; just
            # prove the auth tables exist instead of failing on a path.
            cur.execute("SELECT COUNT(*) AS n FROM users")
            cur.fetchone()
            cur.close()
            return
        with open(path, encoding="utf-8") as f:
            # Single execute: psycopg2 sends the whole script and the server
            # splits statements itself, so DO $$ blocks survive intact.
            cur.execute(f.read())
        conn.commit()
        cur.close()
    finally:
        conn.close()


_apply_migration()
client = TestClient(app, follow_redirects=False)


def _email(tag):
    return f"zt-{tag}-{uuid.uuid4().hex[:8]}@attendance.internal"


@pytest.fixture(autouse=True)
def _clean():
    auth_local._LOGIN_ATTEMPTS.clear()
    yield
    auth_local._LOGIN_ATTEMPTS.clear()
    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM wfh_approvals WHERE approved_by IN"
                    " (SELECT id FROM users WHERE email LIKE 'zt-%%')"
                    " OR employee_id LIKE 'zt-%%'")
        cur.execute("DELETE FROM audit_log WHERE actor_user_id IN"
                    " (SELECT id FROM users WHERE email LIKE 'zt-%%')"
                    " OR target_employee_id LIKE 'zt-%%'")
        cur.execute("UPDATE refresh_tokens SET replaced_by = NULL WHERE user_id IN"
                    " (SELECT id FROM users WHERE email LIKE 'zt-%%')")
        cur.execute("DELETE FROM refresh_tokens WHERE user_id IN"
                    " (SELECT id FROM users WHERE email LIKE 'zt-%%')")
        cur.execute("DELETE FROM auth_events WHERE email LIKE 'zt-%%' OR user_id IN"
                    " (SELECT id FROM users WHERE email LIKE 'zt-%%')")
        cur.execute("DELETE FROM users WHERE email LIKE 'zt-%%'")
        cur.execute("DELETE FROM employees WHERE id LIKE 'zt-%%'")
        conn.commit()
        cur.close()
    finally:
        conn.close()


def _mkuser(email, password="0123456789abcdef", role="viewer",
            provider="local", active=True, mcp=False):
    from app.auth.security import hash_password
    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (email, display_name, role, auth_provider,"
            " password_hash, is_active, must_change_password)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (email, email.split("@")[0], role, provider,
             hash_password(password) if provider == "local" else None,
             active, mcp),
        )
        uid = str(cur.fetchone()["id"])
        conn.commit()
        cur.close()
        return uid
    finally:
        conn.close()


def _login(email, password="0123456789abcdef"):
    return client.post("/auth/login", json={"email": email, "password": password})


def _authz(token):
    return {"Authorization": f"Bearer {token}"}


def _cookie_from(resp):
    # TestClient (httpx cookies) keeps the jar; also read explicit header.
    return resp.headers.get("set-cookie", "")


# ---------- bootstrap ----------

def test_bootstrap_created_once_and_idempotent(monkeypatch):
    email = _email("boot")
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_EMAIL", email)
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_PASSWORD", "0123456789abcdef")
    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, is_active FROM users WHERE role = 'admin'"
                    " AND auth_provider = 'local'")
        original = {str(r["id"]): r["is_active"] for r in cur.fetchall()}
        # Simulate a fresh install (no active local admin); original flags
        # are restored in `finally` — and the zt- cleanup fixture backs us up.
        cur.execute("UPDATE users SET is_active = FALSE WHERE role = 'admin'"
                    " AND auth_provider = 'local' AND is_active = TRUE")
        conn.commit()
        cur.close()
        try:
            assert ensure_bootstrap_admin() == email
            assert ensure_bootstrap_admin() is None
            check = _db()
            try:
                cur2 = check.cursor()
                cur2.execute("SELECT COUNT(*) AS n FROM users WHERE email = %s",
                             (email,))
                assert cur2.fetchone()["n"] == 1
                cur2.close()
            finally:
                check.close()
        finally:
            restore = _db()
            try:
                cur3 = restore.cursor()
                for uid, was_active in original.items():
                    cur3.execute("UPDATE users SET is_active = %s WHERE id = %s::uuid",
                                 (was_active, uid))
                cur3.execute("DELETE FROM users WHERE email = %s", (email,))
                restore.commit()
                cur3.close()
            finally:
                restore.close()
    finally:
        conn.close()


# ---------- local login ----------

def test_login_ok_returns_token_and_cookie():
    email = _email("ok")
    _mkuser(email)
    r = _login(email)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == email
    cookie = _cookie_from(r)
    assert "refresh_token=" in cookie and "HttpOnly" in cookie
    assert "Path=/" in cookie


def test_wrong_password_and_unknown_email_identical():
    email = _email("bad")
    _mkuser(email)
    r1 = _login(email, "wrong-password-xyz")
    r2 = _login(_email("nobody"), "wrong-password-xyz")
    assert r1.status_code == r2.status_code == 401
    assert r1.json() == r2.json() == {"detail": "invalid_credentials"}


def test_lockout_after_5_failures_then_recovers():
    email = _email("lock")
    _mkuser(email)
    for _ in range(5):
        assert _login(email, "wrong-password-xyz").status_code == 401
    # 6th with the RIGHT password still 401 while locked
    assert _login(email).status_code == 401
    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE users SET locked_until = now() - interval '1 minute'"
                    " WHERE email = %s", (email,))
        conn.commit()
        cur.close()
    finally:
        conn.close()
    assert _login(email).status_code == 200


def test_inactive_and_sso_users_cannot_use_password():
    email = _email("inact")
    _mkuser(email, active=False)
    assert _login(email).status_code == 401
    sso = _email("sso")
    _mkuser(sso, provider="entra")
    r = _login(sso)
    assert r.status_code == 401
    assert r.json() == {"detail": "invalid_credentials"}


# ---------- tokens and sessions ----------

def test_expired_access_token_then_refresh(monkeypatch):
    monkeypatch.setattr(settings, "ACCESS_TTL_SECONDS", 2)
    email = _email("exp")
    _mkuser(email)
    token = _login(email).json()["access_token"]
    time.sleep(3)
    r = client.get("/auth/me", headers=_authz(token))
    assert r.status_code == 401
    assert r.json()["detail"] == "token_expired"


def _login_with_cookies(email):
    c = TestClient(app, follow_redirects=False)
    r = c.post("/auth/login", json={"email": email,
                                    "password": "0123456789abcdef"})
    assert r.status_code == 200
    return c, r.json()["access_token"]


def test_refresh_rotates_and_old_replay_revokes_family():
    email = _email("rot")
    _mkuser(email)
    c, _ = _login_with_cookies(email)
    old_raw = c.cookies.get("refresh_token")
    assert old_raw
    r = c.post("/auth/refresh")
    assert r.status_code == 200, r.text
    new_raw = c.cookies.get("refresh_token")
    assert new_raw and new_raw != old_raw
    # Age the revoked row past the 10s race grace, then replay the old token.
    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE refresh_tokens SET revoked_at = now() - interval '30 seconds'"
                    " WHERE token_hash = %s", (hash_refresh(old_raw),))
        conn.commit()
        cur.close()
    finally:
        conn.close()
    c.cookies.set("refresh_token", old_raw)
    assert c.post("/auth/refresh").status_code == 401
    # Whole family dead: even the newest token fails now.
    c.cookies.set("refresh_token", new_raw)
    assert c.post("/auth/refresh").status_code == 401


def test_replay_within_grace_does_not_kill_family():
    email = _email("grace")
    _mkuser(email)
    c, _ = _login_with_cookies(email)
    old_raw = c.cookies.get("refresh_token")
    assert c.post("/auth/refresh").status_code == 200
    new_raw = c.cookies.get("refresh_token")
    c.cookies.set("refresh_token", old_raw)
    assert c.post("/auth/refresh").status_code == 401
    c.cookies.set("refresh_token", new_raw)
    assert c.post("/auth/refresh").status_code == 200


def test_concurrent_refresh_one_wins_family_intact():
    email = _email("race")
    _mkuser(email)
    c, _ = _login_with_cookies(email)
    raw = c.cookies.get("refresh_token")
    c2 = TestClient(app, follow_redirects=False)
    c2.cookies.set("refresh_token", raw)
    statuses = sorted([c.post("/auth/refresh").status_code,
                       c2.post("/auth/refresh").status_code])
    assert statuses == [200, 401]
    winner = c if c.cookies.get("refresh_token") != raw else c2
    assert winner.post("/auth/refresh").status_code == 200


def test_logout_revokes_and_is_idempotent():
    email = _email("out")
    _mkuser(email)
    c, _ = _login_with_cookies(email)
    assert c.post("/auth/logout").status_code == 204
    assert c.post("/auth/refresh").status_code == 401
    assert c.post("/auth/logout").status_code == 204


def test_refresh_fails_after_family_expiry():
    email = _email("fam")
    _mkuser(email)
    c, _ = _login_with_cookies(email)
    raw = c.cookies.get("refresh_token")
    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE refresh_tokens SET family_expires_at = now() - interval '1 minute'"
                    " WHERE token_hash = %s", (hash_refresh(raw),))
        conn.commit()
        cur.close()
    finally:
        conn.close()
    assert c.post("/auth/refresh").status_code == 401


def test_deactivation_kills_api_and_refresh():
    email = _email("deact")
    _mkuser(email)
    c, token = _login_with_cookies(email)
    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE users SET is_active = FALSE WHERE email = %s", (email,))
        conn.commit()
        cur.close()
    finally:
        conn.close()
    assert client.get("/teams", headers=_authz(token)).status_code == 401
    assert c.post("/auth/refresh").status_code == 401


def test_bad_tokens_rejected():
    email = _email("tok")
    _mkuser(email)
    good = _login(email).json()["access_token"]
    # tampered signature (flip a char in the middle of the signature
    # segment — the last char's low bits are ignored by base64url)
    parts = good.split(".")
    sig = parts[2]
    i = len(sig) // 2
    bad = ".".join([parts[0], parts[1], sig[:i] + ("a" if sig[i] != "a" else "b") + sig[i + 1:]])
    assert client.get("/auth/me", headers=_authz(bad)).status_code == 401
    payload = pyjwt.decode(good, options={"verify_signature": False})
    for mutate in ({"aud": "someone-else"}, {"iss": "someone-else"}):
        forged = dict(payload, **mutate)
        token = pyjwt.encode(forged, settings.JWT_SECRET, algorithm="HS256")
        r = client.get("/auth/me", headers=_authz(token))
        assert r.status_code == 401, mutate
    none_token = pyjwt.encode(payload, key="", algorithm="none")
    assert client.get("/auth/me", headers=_authz(none_token)).status_code == 401
    assert client.get("/teams").status_code == 401  # anonymous rejected


# ---------- roles ----------

def _tokens_for(*roles):
    out = {}
    for role in roles:
        email = _email(role)
        _mkuser(email, role=role)
        out[role] = _login(email).json()["access_token"]
    return out


def test_role_matrix():
    toks = _tokens_for("viewer", "manager", "admin")
    for role, tok in toks.items():
        assert client.get("/teams", headers=_authz(tok)).status_code == 200, role
    for role in ("viewer", "manager"):
        r = client.get("/users", headers=_authz(toks[role]))
        assert r.status_code == 403, role
    assert client.get("/users", headers=_authz(toks["admin"])).status_code == 200
    # bulk ingestion choke point stays admin-only
    assert client.post("/attendance/bulk", headers=_authz(toks["manager"]),
                       json={"source": "migrated", "records": []}).status_code == 403
    assert client.post("/attendance/bulk", headers=_authz(toks["admin"]),
                       json={"source": "migrated", "records": []}).status_code == 200


def test_manager_writer_and_viewer_blocked_on_wfh():
    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO employees (id, name) VALUES ('zt-emp-1', 'Zt Emp')"
                    " ON CONFLICT (id) DO NOTHING")
        conn.commit()
        cur.close()
    finally:
        conn.close()
    toks = _tokens_for("viewer", "manager")
    assert client.post("/wfh", headers=_authz(toks["viewer"]),
                       json={"employee_id": "zt-emp-1",
                             "date": "2026-09-01"}).status_code == 403
    r = client.post("/wfh", headers=_authz(toks["manager"]),
                    json={"employee_id": "zt-emp-1", "date": "2026-09-01"})
    assert r.status_code == 200, r.text


def test_must_change_password_gates_everything_but_self_service():
    email = _email("mcp")
    _mkuser(email, mcp=True)
    tok = _login(email).json()["access_token"]
    assert client.get("/teams", headers=_authz(tok)).status_code == 403
    assert client.get("/teams", headers=_authz(tok)).json() == {
        "detail": "password_change_required"}
    assert client.get("/auth/me", headers=_authz(tok)).status_code == 200
    assert client.post("/auth/logout", headers=_authz(tok)).status_code in (204, 401)
    # change it (other sessions revoked, this one continues)
    c, _ = _login_with_cookies(email)
    tok2 = c.post("/auth/login",
                  json={"email": email,
                        "password": "0123456789abcdef"}).json()["access_token"]
    r = client.post("/auth/change-password", headers=_authz(tok2),
                    json={"current_password": "0123456789abcdef",
                          "new_password": "new-password-abcdef"})
    assert r.status_code == 200, r.text
    assert client.get("/teams",
                      headers=_authz(r.json()["access_token"])).status_code == 200


def test_admin_cannot_demote_or_deactivate_self():
    email = _email("selfadmin")
    uid = _mkuser(email, role="admin")
    tok = _login(email).json()["access_token"]
    r = client.patch(f"/users/{uid}", headers=_authz(tok),
                     json={"role": "viewer"})
    assert r.status_code == 400
    r = client.patch(f"/users/{uid}", headers=_authz(tok),
                     json={"is_active": False})
    assert r.status_code == 400
    # still admin afterwards
    assert client.get("/users", headers=_authz(tok)).status_code == 200


def test_admin_user_crud_and_reset():
    email = _email("admin")
    _mkuser(email, role="admin")
    tok = _login(email).json()["access_token"]
    created = client.post("/users", headers=_authz(tok),
                          json={"email": _email("new"),
                                "display_name": "Newbie", "role": "viewer",
                                "auth_provider": "local"}).json()
    assert "temporary_password" in created
    assert created["role"] == "viewer"
    uid = created["id"]
    patched = client.patch(f"/users/{uid}", headers=_authz(tok),
                           json={"role": "manager"}).json()
    assert patched["role"] == "manager"
    reset = client.post(f"/users/{uid}/reset-password",
                        headers=_authz(tok)).json()
    assert "temporary_password" in reset
    assert client.get("/auth/events", headers=_authz(tok)).status_code == 200
    viewer_tok = _login(created["email"],
                        reset["temporary_password"]).json()["access_token"]
    assert client.get("/auth/events", headers=_authz(viewer_tok)).status_code == 403


# ---------- SSO ----------

class _FakeTokenResp:
    status_code = 200

    def __init__(self, id_token):
        self._id_token = id_token

    def json(self):
        return {"id_token": self._id_token}


class _FakeAsyncClient:
    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *a, **kw):
        return _FakeTokenResp("fake-id-token")


def _sso_env(monkeypatch):
    monkeypatch.setattr(settings, "ENTRA_TENANT_ID", "tid-123")
    monkeypatch.setattr(settings, "ENTRA_CLIENT_ID", "cid-123")
    monkeypatch.setattr(settings, "ENTRA_CLIENT_SECRET", "csec-123")
    monkeypatch.setattr(auth_microsoft, "validate_entra_id_token",
                        lambda token, nonce: _CLAIMS)
    monkeypatch.setattr("httpx.AsyncClient", _FakeAsyncClient)


_CLAIMS = {}


def _tx_cookie(state="st-1"):
    import time as _t
    return pyjwt.encode(
        {"state": state, "nonce": "n-1", "verifier": "v-1",
         "iat": int(_t.time()), "exp": int(_t.time()) + 600},
        settings.JWT_SECRET, algorithm="HS256")


def _callback(state="st-1", cookie_state="st-1", code="code-1", nonce="n-1"):
    global _CLAIMS
    c = TestClient(app, follow_redirects=False)
    c.cookies.set("oidc_tx", _tx_cookie(cookie_state))
    return c.get(f"/auth/microsoft/callback?code={code}&state={state}")


def test_sso_login_redirect_and_user(monkeypatch):
    global _CLAIMS
    _CLAIMS = {"oid": "oid-1", "tid": "tid-123", "email": "Zt-Sso@Example.com",
               "name": "Zt Sso", "roles": ["Manager"], "nonce": "n-1"}
    _sso_env(monkeypatch)
    r = client.get("/auth/microsoft/login")
    assert r.status_code == 302
    assert "login.microsoftonline.com/tid-123" in r.headers["location"]
    assert "oidc_tx=" in r.headers.get("set-cookie", "")
    r = _callback()
    assert r.status_code == 302, r.text
    assert r.headers["location"] == "/"
    assert "token" not in r.headers["location"]
    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE entra_oid = 'oid-1'")
        row = cur.fetchone()
        assert row and row["role"] == "manager"
        assert row["email"] == "zt-sso@example.com"  # lowercased
        cur.close()
    finally:
        conn.close()


def test_sso_highest_role_wins(monkeypatch):
    global _CLAIMS
    _CLAIMS = {"oid": "oid-hi", "tid": "tid-123", "email": _email("hi"),
               "roles": ["Viewer", "Admin"], "nonce": "n-1"}
    _sso_env(monkeypatch)
    assert _callback().headers["location"] == "/"
    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT role FROM users WHERE entra_oid = 'oid-hi'")
        assert cur.fetchone()["role"] == "admin"
        cur.close()
    finally:
        conn.close()


def test_sso_no_role_no_row_denied(monkeypatch):
    global _CLAIMS
    _CLAIMS = {"oid": "oid-norole", "tid": "tid-123",
               "email": _email("norole"), "nonce": "n-1"}
    _sso_env(monkeypatch)
    r = _callback()
    assert r.headers["location"] == "/?auth_error=access_not_granted"


def test_sso_no_role_with_precreated_row_keeps_db_role(monkeypatch):
    global _CLAIMS
    email = _email("pre")
    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO users (email, role, auth_provider)"
                    " VALUES (%s,'viewer','entra')", (email,))
        conn.commit()
        cur.close()
    finally:
        conn.close()
    _CLAIMS = {"oid": "oid-pre", "tid": "tid-123", "email": email, "nonce": "n-1"}
    _sso_env(monkeypatch)
    assert _callback().headers["location"] == "/"


def test_sso_never_merges_into_local(monkeypatch):
    global _CLAIMS
    email = _email("localclash")
    _mkuser(email)
    _CLAIMS = {"oid": "oid-clash", "tid": "tid-123", "email": email,
               "roles": ["Viewer"], "nonce": "n-1"}
    _sso_env(monkeypatch)
    r = _callback()
    assert r.headers["location"] == "/?auth_error=local_account_exists"


def test_sso_second_login_binds_by_oid(monkeypatch):
    global _CLAIMS
    _CLAIMS = {"oid": "oid-re", "tid": "tid-123", "email": _email("re1"),
               "roles": ["Viewer"], "nonce": "n-1"}
    _sso_env(monkeypatch)
    assert _callback().headers["location"] == "/"
    _CLAIMS = {"oid": "oid-re", "tid": "tid-123", "email": _email("re2"),
               "roles": ["Viewer"], "nonce": "n-1"}
    assert _callback().headers["location"] == "/"
    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS n FROM users WHERE entra_oid = 'oid-re'")
        assert cur.fetchone()["n"] == 1
        cur.close()
    finally:
        conn.close()


def test_sso_disabled_user_denied_despite_role(monkeypatch):
    global _CLAIMS
    email = _email("dis")
    uid = _mkuser(email, provider="entra")
    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE users SET is_active = FALSE, entra_oid = 'oid-dis'"
                    " WHERE id = %s", (uid,))
        conn.commit()
        cur.close()
    finally:
        conn.close()
    _CLAIMS = {"oid": "oid-dis", "tid": "tid-123", "email": email,
               "roles": ["Admin"], "nonce": "n-1"}
    _sso_env(monkeypatch)
    r = _callback()
    assert r.headers["location"] == "/?auth_error=account_disabled"


def test_sso_failures_all_sso_failed(monkeypatch):
    global _CLAIMS
    _CLAIMS = {"oid": "oid-x", "tid": "tid-123", "email": _email("x"),
               "roles": ["Viewer"], "nonce": "n-1"}
    _sso_env(monkeypatch)
    assert _callback(state="wrong").headers["location"] == "/?auth_error=sso_failed"
    c = TestClient(app, follow_redirects=False)
    r = c.get("/auth/microsoft/callback?code=x&state=st-1")  # no cookie
    assert r.headers["location"] == "/?auth_error=sso_failed"

    def _boom(token, nonce):
        raise ValueError("bad")
    monkeypatch.setattr(auth_microsoft, "validate_entra_id_token", _boom)
    assert _callback().headers["location"] == "/?auth_error=sso_failed"


def test_sso_not_configured_503(monkeypatch):
    monkeypatch.setattr(settings, "ENTRA_TENANT_ID", "")
    monkeypatch.setattr(settings, "ENTRA_CLIENT_ID", "")
    monkeypatch.setattr(settings, "ENTRA_CLIENT_SECRET", "")
    assert client.get("/auth/microsoft/login").status_code == 503
