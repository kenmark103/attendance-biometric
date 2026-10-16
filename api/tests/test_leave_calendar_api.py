"""GET /leave/calendar + coverage-extension tests. Compose Postgres needed.

Run: docker compose exec api pytest tests/test_leave_calendar_api.py -v
All rows are zt-scoped; cleanup wipes them. Nothing touches real data.
"""
import io
import os
import sys
import uuid
from pathlib import Path

import pytest

os.environ.setdefault("JWT_SECRET", "test-secret-0123456789abcdef-test-secret")
os.environ.setdefault("DATABASE_URL",
                      "postgresql://attendance:attendance@localhost:5434/attendance")

pytestmark = pytest.mark.db

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from fastapi.testclient import TestClient  # noqa: E402

from app.core.db import get_conn  # noqa: E402
from app.main import app  # noqa: E402

openpyxl = pytest.importorskip("openpyxl")
import make_leave_fixture as fix  # noqa: E402

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean():
    from app.auth import local as auth_local
    auth_local._LOGIN_ATTEMPTS.clear()
    keep = _coverage_snapshot()
    yield
    auth_local._LOGIN_ATTEMPTS.clear()
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM calendar_day_change WHERE employee_id LIKE 'zt-%%'")
        cur.execute("DELETE FROM calendar_day WHERE employee_id LIKE 'zt-%%'")
        cur.execute("DELETE FROM leave_coverage WHERE batch_id IN"
                    " (SELECT id FROM leave_import WHERE original_filename LIKE 'zt-%%')")
        cur.execute("DELETE FROM leave_import WHERE original_filename LIKE 'zt-%%'")
        cur.execute("DELETE FROM refresh_tokens WHERE user_id IN"
                    " (SELECT id FROM users WHERE email LIKE 'zt-%%')")
        cur.execute("DELETE FROM users WHERE email LIKE 'zt-%%'")
        conn.commit()
        cur.close()
    finally:
        conn.close()
    _coverage_restore(keep)


def _coverage_snapshot():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT source, through_date, batch_id FROM leave_coverage")
        rows = [(r["source"], str(r["through_date"]), r["batch_id"]) for r in cur.fetchall()]
        cur.close()
        return rows
    finally:
        conn.close()


def _coverage_restore(keep):
    conn = get_conn()
    try:
        cur = conn.cursor()
        for source, through, batch in keep:
            cur.execute("SELECT 1 FROM leave_import WHERE id = %s", (batch,))
            if cur.fetchone() is None:
                continue
            cur.execute("INSERT INTO leave_coverage (source, through_date, batch_id)"
                        " VALUES (%s, %s, %s) ON CONFLICT (source) DO NOTHING",
                        (source, through, batch))
        conn.commit()
        cur.close()
    finally:
        conn.close()


def _mkuser(email, role="admin", password="0123456789abcdef"):
    from app.auth.security import hash_password
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (email, display_name, role, auth_provider,"
            " password_hash, is_active, must_change_password)"
            " VALUES (%s,%s,%s,'local',%s,TRUE,FALSE) RETURNING id",
            (email, email.split("@")[0], role, hash_password(password)))
        uid = str(cur.fetchone()["id"])
        conn.commit()
        cur.close()
        return uid
    finally:
        conn.close()


def _headers(role="admin"):
    email = f"zt-{role}-{uuid.uuid4().hex[:8]}@attendance.internal"
    _mkuser(email, role=role)
    r = client.post("/auth/login",
                    json={"email": email, "password": "0123456789abcdef"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _seed_committed(tag, headers):
    g = fix.build_grid(2026, 1, 2, set(), 0)
    g[7][0] = f"zt-{tag}-90001"
    g[8][0] = f"zt-{tag}-90002"
    g[7][2 + 4] = "EL"  # Mon 5 Jan: leave for employee 1
    buf = io.BytesIO()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Jan"
    for row in g:
        ws.append(row)
    wb.save(buf)
    up = client.post("/leave/imports",
                     files={"file": (f"zt-{tag}.xlsx", buf.getvalue(),
                                     "application/octet-stream")},
                     headers=headers)
    assert up.status_code == 200, up.text
    iid = up.json()["import_id"]
    co = client.post(f"/leave/imports/{iid}/commit", json={}, headers=headers)
    assert co.status_code == 200, co.text
    return f"zt-{tag}-90001", f"zt-{tag}-90002"


def test_calendar_admin_sees_leave_detail():
    h, tag = _headers("admin"), uuid.uuid4().hex[:8]
    emp1, _emp2 = _seed_committed(tag, h)
    # NOTE: the dev DB may hold real backfill rows; scope to our own IDs.
    r = client.get("/leave/calendar", params={"employee_id": emp1}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 31
    leave_days = [d for d in body["days"] if d["day_kind"] == "leave"]
    assert len(leave_days) == 1
    assert leave_days[0]["employee_id"] == emp1
    assert leave_days[0]["leave_type"] == "Annual Leave"
    assert leave_days[0]["leave_fraction"] == 1.0
    work = [d for d in body["days"] if d["day_kind"] == "working"][0]
    assert work["leave_type"] is None
    assert work["zoho_presence"] is True  # single P carries presence=true


def test_calendar_viewer_gets_generic_on_leave():
    _seed_committed(uuid.uuid4().hex[:8], _headers("admin"))
    h = _headers("viewer")
    r = client.get("/leave/calendar", headers=h)
    assert r.status_code == 200, r.text
    leave_days = [d for d in r.json()["days"] if d["day_kind"] == "leave"]
    assert leave_days and all(d["leave_type"] == "On leave" for d in leave_days)


def test_calendar_filters_and_pagination():
    h, tag = _headers("admin"), uuid.uuid4().hex[:8]
    emp1, _emp2 = _seed_committed(tag, h)
    r = client.get("/leave/calendar",
                   params={"employee_id": emp1, "date_from": "2026-01-05",
                           "date_to": "2026-01-05"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 1
    assert r.json()["days"][0]["raw_code"] == "EL"
    r = client.get("/leave/calendar", params={"limit": 10, "offset": 0}, headers=h)
    assert len(r.json()["days"]) == 10 and r.json()["total"] >= 2 * 31


def test_calendar_source_priority_api_over_xls():
    h, tag = _headers("admin"), uuid.uuid4().hex[:8]
    emp1, _emp2 = _seed_committed(tag, h)
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO calendar_day (employee_id, date, source, raw_code,"
                    " kind) VALUES (%s, '2026-01-06', 'api', 'EL', 'leave')",
                    (emp1,))
        conn.commit()
        cur.close()
    finally:
        conn.close()
    r = client.get("/leave/calendar",
                   params={"employee_id": emp1, "date_from": "2026-01-06",
                           "date_to": "2026-01-06"}, headers=h)
    assert r.json()["total"] == 1
    assert r.json()["days"][0]["source"] == "api"
    assert r.json()["days"][0]["raw_code"] == "EL"


def test_calendar_unauthenticated():
    assert client.get("/leave/calendar").status_code in (401, 403)


def test_stats_coverage_carries_leave_signal():
    h, tag = _headers("admin"), uuid.uuid4().hex[:8]
    _seed_committed(tag, h)
    r = client.get("/stats/coverage", headers=_headers("viewer"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["leave_coverage"]["through_date"] >= "2026-01-31"
    assert body["leave_coverage"]["source"] == "xls"
    assert body["trust_zoho_presence"] is True
