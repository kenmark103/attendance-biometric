"""Leave-import preview API tests. Needs the compose Postgres + 007/008.

Run: docker compose exec api pytest tests/test_leave_import_api.py -v
Filenames are zt-prefixed; cleanup removes those imports (staging and
issues cascade). Fixture IDs never reach calendar_day before commit, so no
attendance data is touched.
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
from app.leave.parsing import parse_leave_workbook  # noqa: E402

MIGRATIONS = ["db/migrations/007_leave_ingestion.sql",
              "db/migrations/008_leave_preview_names.sql"]


def _apply_migrations():
    conn = get_conn()
    try:
        cur = conn.cursor()
        for rel in MIGRATIONS:
            path = Path("/app") / rel if Path("/app", rel).exists() else Path(rel)
            with open(path, encoding="utf-8") as f:
                cur.execute(f.read())
        conn.commit()
        cur.close()
    finally:
        conn.close()


_apply_migrations()
client = TestClient(app)


def _db():
    return get_conn()


@pytest.fixture(autouse=True)
def _clean():
    from app.auth import local as auth_local
    auth_local._LOGIN_ATTEMPTS.clear()
    yield
    auth_local._LOGIN_ATTEMPTS.clear()
    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM leave_import WHERE original_filename LIKE 'zt-%%'")
        cur.execute("DELETE FROM refresh_tokens WHERE user_id IN"
                    " (SELECT id FROM users WHERE email LIKE 'zt-%%')")
        cur.execute("DELETE FROM auth_events WHERE email LIKE 'zt-%%'")
        cur.execute("DELETE FROM users WHERE email LIKE 'zt-%%'")
        conn.commit()
        cur.close()
    finally:
        conn.close()


def _mkuser(email, role="admin", password="0123456789abcdef"):
    from app.auth.security import hash_password
    conn = _db()
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


def _xlsx_bytes(**kw):
    months = kw.pop("months", 1)
    employees = kw.pop("employees", 4)
    edges = kw.pop("edges", set())
    grid = fix.build_grid(2026, 1, employees, edges, 0)
    sheets = [("Jan", grid)]
    for i in range(1, months):
        sheets.append((f"M{i + 1}", fix.build_grid(2026, 1 + i, employees,
                                                   edges, i)))
    buf = io.BytesIO()
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, g in sheets:
        ws = wb.create_sheet(title=name)
        for row in g:
            ws.append(row)
    wb.save(buf)
    return buf.getvalue()


def _upload(data, filename, headers):
    return client.post("/leave/imports",
                       files={"file": (filename, data,
                                       "application/octet-stream")},
                       headers=headers)


def _zt_name(ext="xlsx"):
    return f"zt-{uuid.uuid4().hex[:8]}.{ext}"


def test_upload_xlsx_preview_ready():
    h = _headers()
    r = _upload(_xlsx_bytes(), _zt_name(), h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "preview_ready"
    assert body["already_imported"] is False
    assert body["counts"]["total"] == 4 * 31
    assert body["counts"]["new"] == 4 * 31
    assert body["coverage_through"] == "2026-01-31"
    assert len(body["sheets"]) == 1 and not body["sheets"][0]["blocked"]
    # preview names available in-flight, IDs-only in issues
    assert body["preview_names"]["90001"] == "Test User 1"


def test_reupload_same_file_is_noop():
    h = _headers()
    data = _xlsx_bytes()
    first = _upload(data, _zt_name(), h).json()
    second = _upload(data, _zt_name(), h).json()
    assert second["already_imported"] is True
    assert second["import_id"] == first["import_id"]


def test_wrong_extension_415():
    h = _headers()
    r = _upload(b"whatever", _zt_name("csv"), h)
    assert r.status_code == 415


def test_corrupt_xlsx_422():
    h = _headers()
    r = _upload(b"PK\x03\x04this-is-not-a-workbook", _zt_name(), h)
    assert r.status_code == 422


def test_too_large_413():
    h = _headers()
    r = _upload(b"x" * (10 * 1024 * 1024 + 1), _zt_name(), h)
    assert r.status_code == 413


def test_unauthenticated_401_and_viewer_403():
    r = client.post("/leave/imports",
                    files={"file": ("zt-a.xlsx", b"PK", "application/octet-stream")})
    assert r.status_code in (401, 403)
    r = _upload(_xlsx_bytes(), _zt_name(), _headers(role="viewer"))
    assert r.status_code == 403


def test_issues_filter_and_pagination():
    h = _headers()
    imp = _upload(_xlsx_bytes(edges={"unknown"}), _zt_name(), h).json()
    iid = imp["import_id"]
    r = client.get(f"/leave/imports/{iid}/issues",
                   params={"severity": "warning"}, headers=h)
    assert r.status_code == 200, r.text
    codes = {i["code"] for i in r.json()["issues"]}
    assert "CELL_UNKNOWN_CODE" in codes
    # unknown IDs are not in the directory
    assert "EMPLOYEE_NOT_IN_SYSTEM" in codes
    r = client.get(f"/leave/imports/{iid}/issues",
                   params={"code": "CELL_UNKNOWN_CODE", "limit": 1},
                   headers=h)
    body = r.json()
    assert body["total"] == 1 and len(body["issues"]) == 1
    assert body["issues"][0]["occurrences"] >= 1
    assert r.status_code == 200


def test_changes_all_new_on_first_upload():
    h = _headers()
    iid = _upload(_xlsx_bytes(), _zt_name(), h).json()["import_id"]
    for t, want_new in (("new", True), ("changed", False), ("leave_removed", False)):
        r = client.get(f"/leave/imports/{iid}/changes",
                       params={"type": t}, headers=h)
        assert r.status_code == 200, r.text
        total = r.json()["total"]
        if want_new:
            assert total == 4 * 31
        else:
            assert total == 0
    r = client.get(f"/leave/imports/{iid}/changes",
                   params={"limit": 5}, headers=h)
    row = r.json()["changes"][0]
    assert row["change_type"] == "new" and row["old_raw"] is None


def test_html_disguised_upload():
    h = _headers()
    grid = fix.build_grid(2026, 1, 2, set(), 0)
    cells = "".join("<tr>" + "".join(f"<td>{v}</td>" for v in row) + "</tr>"
                    for row in grid)
    data = f"<html><body><table>{cells}</table></body></html>".encode()
    r = _upload(data, _zt_name("xls"), h)
    assert r.status_code == 200, r.text
    assert r.json()["counts"]["total"] == 2 * 31


def test_provisional_column_excluded():
    h = _headers()
    imp = _upload(_xlsx_bytes(months=2, edges={"provisional"}), _zt_name(), h).json()
    assert imp["coverage_through"] == "2026-02-27"
    assert imp["counts"]["total"] == 4 * 31 + 4 * 27
    r = client.get(f"/leave/imports/{imp['import_id']}/issues",
                   params={"code": "LAST_COLUMN_PROVISIONAL"}, headers=h)
    assert r.json()["total"] == 1


def test_history_and_coverage():
    h = _headers()
    imp = _upload(_xlsx_bytes(), _zt_name(), h).json()
    r = client.get("/leave/imports", headers=h)
    assert r.status_code == 200
    assert any(i["import_id"] if "import_id" in i else i["id"] == imp["import_id"]
               for i in r.json())
    r = client.get("/leave/coverage", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"through_date", "last_import_at", "source"}


def test_template_sample_parses():
    h = _headers()
    r = client.get("/leave/template-sample", headers=h)
    assert r.status_code == 200
    assert "spreadsheetml" in r.headers["content-type"]
    code_map = {"P": {"kind": "working", "leave_group": None},
                "W": {"kind": "weekend", "leave_group": None},
                "EL": {"kind": "leave", "leave_group": "annual"},
                "SL": {"kind": "leave", "leave_group": "sick"}}
    parsed = parse_leave_workbook(r.content, code_map, {"whatever"})
    assert len(parsed.sheets) == 1 and not parsed.sheets[0].blocked
    assert len(parsed.sheets[0].rows) == 3 * 31


def test_import_not_found_404():
    h = _headers()
    assert client.get("/leave/imports/999999999", headers=h).status_code == 404
    assert client.get("/leave/imports/999999999/issues", headers=h).status_code == 404
    assert client.get("/leave/imports/999999999/changes", headers=h).status_code == 404
