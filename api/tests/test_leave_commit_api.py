"""Leave commit/revert/janitor tests. Needs the compose Postgres + 007-009.

Run: docker compose exec api pytest tests/test_leave_commit_api.py -v
All employee IDs are zt-prefixed; cleanup wipes zt- rows from calendar,
audit, staging parents, employees and users. Nothing touches real data.
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

for _rel in ("db/migrations/007_leave_ingestion.sql",
             "db/migrations/008_leave_preview_names.sql",
             "db/migrations/009_leave_idempotency.sql"):
    _p = Path("/app", _rel) if Path("/app", _rel).exists() else Path(_rel)
    _conn = get_conn()
    try:
        _cur = _conn.cursor()
        _cur.execute(_p.read_text(encoding="utf-8"))
        _conn.commit()
        _cur.close()
    finally:
        _conn.close()

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
        cur.execute("DELETE FROM employees WHERE id LIKE 'zt-%%'")
        cur.execute("DELETE FROM leave_code_map WHERE code LIKE 'ZZ%%'")
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
    """Put back the shared (e.g. backfill) coverage row if tests removed it."""
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
    role = {"admin": "Admin", "viewer": "Viewer"}.get(role, role)
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


def _tag():
    return uuid.uuid4().hex[:8]


def _grid(year, month, n, edges, idx, tag):
    g = fix.build_grid(year, month, n, edges, idx)
    mapping: dict[str, str] = {}
    for r in range(7, len(g)):
        row = g[r]
        if not row or not str(row[0]).strip():
            continue
        orig = str(row[0]).strip()
        mapping.setdefault(orig, f"zt-{tag}-{orig}")
        row[0] = mapping[orig]
    return g


def _workbook_bytes(sheets):
    buf = io.BytesIO()
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, grid in sheets:
        ws = wb.create_sheet(title=name)
        for row in grid:
            ws.append(row)
    wb.save(buf)
    return buf.getvalue()


def _upload(data, filename, headers):
    return client.post("/leave/imports",
                       files={"file": (filename, data, "application/octet-stream")},
                       headers=headers)


def _commit(iid, headers, body=None):
    return client.post(f"/leave/imports/{iid}/commit",
                       json=body or {}, headers=headers)


def _cal_rows(tag):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT employee_id, date, raw_code, kind FROM calendar_day "
                    "WHERE employee_id LIKE %s ORDER BY employee_id, date",
                    (f"zt-{tag}-%",))
        rows = cur.fetchall()
        cur.close()
        return rows
    finally:
        conn.close()


def _jan(year=2026, month=1, n=2, edges=frozenset(), idx=0, tag="t"):
    return _grid(year, month, n, set(edges), idx, tag)


# --- commit happy path -------------------------------------------------------


def test_commit_writes_calendar_and_coverage():
    h, tag = _headers(), _tag()
    data = _workbook_bytes([("Jan", _jan(tag=tag))])
    iid = _upload(data, f"zt-{tag}.xlsx", h).json()["import_id"]
    r = _commit(iid, h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "committed" and body["committed_rows"] == 2 * 31
    assert body["coverage_through"] == "2026-01-31"
    assert len(_cal_rows(tag)) == 2 * 31
    # Global coverage is the max of everything committed (a backfill may exist).
    assert client.get("/leave/coverage", headers=h).json()["through_date"] >= "2026-01-31"
    # staging purged, preview names nulled
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS n FROM leave_import_staging WHERE import_id = %s",
                    (iid,))
        assert cur.fetchone()["n"] == 0
        cur.execute("SELECT preview_names FROM leave_import WHERE id = %s", (iid,))
        assert cur.fetchone()["preview_names"] is None
        cur.close()
    finally:
        conn.close()


def test_commit_selected_sheets_only():
    h, tag = _headers(), _tag()
    data = _workbook_bytes([("Jan", _jan(tag=tag)),
                            ("Feb", _grid(2026, 2, 2, set(), 1, tag))])
    iid = _upload(data, f"zt-{tag}.xlsx", h).json()["import_id"]
    r = _commit(iid, h, {"sheets": ["Jan"]})
    assert r.status_code == 200, r.text
    assert r.json()["coverage_through"] == "2026-01-31"
    assert len(_cal_rows(tag)) == 2 * 31


def test_commit_blocked_sheet_rejected():
    h, tag = _headers(), _tag()
    data = _workbook_bytes([("Jan", _grid(2026, 1, 2, {"duplicate_conflict"}, 0, tag))])
    body = _upload(data, f"zt-{tag}.xlsx", h).json()
    assert body["sheets"][0]["blocked"] is True
    r = _commit(body["import_id"], h, {"sheets": ["Jan"]})
    assert r.status_code == 422


def test_corrected_month_updates_and_flags_past_change():
    h, tag = _headers(), _tag()
    v1 = _workbook_bytes([("Jan", _jan(tag=tag))])
    iid1 = _upload(v1, f"zt-{tag}-v1.xlsx", h).json()["import_id"]
    assert _commit(iid1, h).status_code == 200
    v2grid = _jan(tag=tag)
    v2grid[7][2 + 4] = "EL"  # employee 1, 4 Jan: P -> EL
    v2 = _workbook_bytes([("Jan", v2grid)])
    prev = _upload(v2, f"zt-{tag}-v2.xlsx", h).json()
    assert prev["counts"]["changed"] == 1 and prev["counts"]["past_changed"] == 1
    codes = {i["code"] for i in
             client.get(f"/leave/imports/{prev['import_id']}/issues",
                        headers=h).json()["issues"]}
    assert "PAST_DAYS_CHANGED" in codes
    assert _commit(prev["import_id"], h).status_code == 200
    rows = {(str(r["date"]), r["raw_code"]) for r in _cal_rows(tag)
            if r["employee_id"] == f"zt-{tag}-90001"}
    assert ("2026-01-05", "EL") in rows


def test_leave_removed_on_cancellation():
    h, tag = _headers(), _tag()
    g1 = _jan(tag=tag)
    g1[7][2 + 4] = "EL"
    iid1 = _upload(_workbook_bytes([("Jan", g1)]), f"zt-{tag}-v1.xlsx", h).json()["import_id"]
    assert _commit(iid1, h).status_code == 200
    v2 = _workbook_bytes([("Jan", _jan(tag=tag))])  # EL back to P
    prev = _upload(v2, f"zt-{tag}-v2.xlsx", h).json()
    assert prev["counts"]["leave_removed"] == 1
    assert _commit(prev["import_id"], h).status_code == 200
    rows = {(str(r["date"]), r["raw_code"], r["kind"]) for r in _cal_rows(tag)
            if r["employee_id"] == f"zt-{tag}-90001"}
    assert ("2026-01-05", "P", "working") in rows


# --- guards ------------------------------------------------------------------


def test_large_change_requires_confirm():
    h, tag = _headers(), _tag()
    v1 = _workbook_bytes([("Jan", _jan(tag=tag))])
    assert _commit(_upload(v1, f"zt-{tag}-v1.xlsx", h).json()["import_id"], h).status_code == 200
    g2 = _jan(tag=tag)
    for r in range(7, len(g2)):
        for c in range(2, len(g2[r])):
            if g2[r][c] == "P":
                g2[r][c] = "EL"
    prev = _upload(_workbook_bytes([("Jan", g2)]), f"zt-{tag}-v2.xlsx", h).json()
    codes = {i["code"] for i in
             client.get(f"/leave/imports/{prev['import_id']}/issues",
                        headers=h).json()["issues"]}
    assert "LARGE_CHANGE" in codes
    r = _commit(prev["import_id"], h)
    assert r.status_code == 422 and "LARGE_CHANGE" in r.text
    r = _commit(prev["import_id"], h, {"confirm_large_change": True})
    assert r.status_code == 200, r.text


def test_department_mismatch_requires_ack():
    h, tag = _headers(), _tag()
    g = _jan(tag=tag)
    g[0][1] = "SOME OTHER DEPT"
    prev = _upload(_workbook_bytes([("Jan", g)]), f"zt-{tag}.xlsx", h).json()
    codes = {i["code"] for i in
             client.get(f"/leave/imports/{prev['import_id']}/issues",
                        headers=h).json()["issues"]}
    assert "DEPARTMENT_MISMATCH" in codes
    assert _commit(prev["import_id"], h).status_code == 422
    assert _commit(prev["import_id"], h, {"acknowledge_department": True}).status_code == 200


def test_stale_preview_409():
    h, tag = _headers(), _tag()
    a = _upload(_workbook_bytes([("Jan", _jan(tag=tag))]),
                f"zt-{tag}-a.xlsx", h).json()["import_id"]
    gb = _jan(tag=tag)
    gb[8][2 + 4] = "SL"  # different bytes, so B is its own import
    b = _upload(_workbook_bytes([("Jan", gb)]),
                f"zt-{tag}-b.xlsx", h).json()["import_id"]
    assert b != a
    assert _commit(b, h).status_code == 200
    r = _commit(a, h)
    assert r.status_code == 409 and "BASE_VERSION_STALE" in r.text


def test_concurrent_commit_409():
    h, tag = _headers(), _tag()
    iid = _upload(_workbook_bytes([("Jan", _jan(tag=tag))]),
                  f"zt-{tag}.xlsx", h).json()["import_id"]
    holder = get_conn()
    holder.autocommit = True
    try:
        cur = holder.cursor()
        cur.execute("SELECT pg_advisory_lock(727002)")
        r = _commit(iid, h)
        assert r.status_code == 409 and "IMPORT_IN_PROGRESS" in r.text
    finally:
        cur.execute("SELECT pg_advisory_unlock(727002)")
        cur.close()
        holder.close()
    assert _commit(iid, h).status_code == 200


def test_idempotent_retry_same_key():
    h, tag = _headers(), _tag()
    iid = _upload(_workbook_bytes([("Jan", _jan(tag=tag))]),
                  f"zt-{tag}.xlsx", h).json()["import_id"]
    key = f"zt-key-{tag}"
    first = _commit(iid, h, {"idempotency_key": key})
    assert first.status_code == 200, first.text
    second = _commit(iid, h, {"idempotency_key": key})
    assert second.status_code == 200
    assert second.json()["import_id"] == iid


def test_discard_then_commit_refused():
    h, tag = _headers(), _tag()
    iid = _upload(_workbook_bytes([("Jan", _jan(tag=tag))]),
                  f"zt-{tag}.xlsx", h).json()["import_id"]
    r = client.post(f"/leave/imports/{iid}/discard", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "discarded"
    assert _commit(iid, h).status_code == 422
    assert len(_cal_rows(tag)) == 0


def test_coverage_never_decreases_and_regression_warned():
    h, tag = _headers(), _tag()
    before = client.get("/leave/coverage", headers=h).json()["through_date"]
    jan = _workbook_bytes([("Jan", _jan(tag=tag))])
    assert _commit(_upload(jan, f"zt-{tag}-jan.xlsx", h).json()["import_id"], h).status_code == 200
    dec = _workbook_bytes([("Dec", _grid(2025, 12, 2, set(), 0, tag))])
    prev = _upload(dec, f"zt-{tag}-dec.xlsx", h).json()
    codes = {i["code"] for i in
             client.get(f"/leave/imports/{prev['import_id']}/issues",
                        headers=h).json()["issues"]}
    if before and before > "2025-12-31":
        assert "PERIOD_REGRESSION" in codes
    assert _commit(prev["import_id"], h).status_code == 200
    after = client.get("/leave/coverage", headers=h).json()["through_date"]
    # Coverage never decreases: it is the max of what was there and January.
    assert after == max([t for t in (before, "2026-01-31") if t])


# --- revert ------------------------------------------------------------------


def test_revert_restores_and_deletes():
    h, tag = _headers(), _tag()
    iid0 = _upload(_workbook_bytes([("Jan", _jan(tag=tag))]),
                   f"zt-{tag}-v0.xlsx", h).json()["import_id"]
    assert _commit(iid0, h).status_code == 200
    g1 = _jan(tag=tag)
    g1[7][2 + 4] = "EL"  # Mon 5 Jan: P -> EL
    iid1 = _upload(_workbook_bytes([("Jan", g1)]), f"zt-{tag}-v1.xlsx", h).json()["import_id"]
    assert _commit(iid1, h).status_code == 200
    feb = _workbook_bytes([("Feb", _grid(2026, 2, 2, set(), 1, tag))])
    iid2 = _upload(feb, f"zt-{tag}-v2.xlsx", h).json()["import_id"]
    assert _commit(iid2, h).status_code == 200
    # only the latest committed import may be reverted
    assert client.post(f"/leave/imports/{iid1}/revert", headers=h).status_code == 409
    r = client.post(f"/leave/imports/{iid2}/revert", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["restored"] == 2 * 28 and r.json()["skipped"] == 0
    assert len(_cal_rows(tag)) == 2 * 31  # Feb rows deleted
    # Revert re-derives coverage from the rows that remain (backfill plus
    # any later manual commits), whatever the current state is.
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT MAX(date) AS m FROM calendar_day")
        cal_max = str(cur.fetchone()["m"])
        cur.close()
    finally:
        conn.close()
    assert client.get("/leave/coverage", headers=h).json()["through_date"] == cal_max
    # now v1 is the latest: revert restores the pre-leave value
    r = client.post(f"/leave/imports/{iid1}/revert", headers=h)
    assert r.status_code == 200, r.text
    rows = {(str(x["date"]), x["raw_code"]) for x in _cal_rows(tag)
            if x["employee_id"] == f"zt-{tag}-90001"}
    assert ("2026-01-05", "P") in rows


def test_revert_skips_overwritten_days():
    h, tag = _headers(), _tag()
    iid = _upload(_workbook_bytes([("Jan", _jan(tag=tag))]),
                  f"zt-{tag}.xlsx", h).json()["import_id"]
    assert _commit(iid, h).status_code == 200
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE calendar_day SET raw_code = 'EL' "
                    "WHERE employee_id = %s AND date = '2026-01-05'",
                    (f"zt-{tag}-90001",))
        conn.commit()
        cur.close()
    finally:
        conn.close()
    r = client.post(f"/leave/imports/{iid}/revert", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["skipped"] == 1


# --- types + reprocess --------------------------------------------------------


def test_types_upsert_and_reprocess():
    h, tag = _headers(), _tag()
    code = f"ZZ{tag[:4]}".upper()  # unique per run; never collides with the seed map
    r = client.get("/leave/types", headers=h)
    assert r.status_code == 200 and any(t["code"] == "EL" for t in r.json())
    g = _jan(tag=tag)
    g[7][2 + 4] = code  # unknown today
    iid = _upload(_workbook_bytes([("Jan", g)]), f"zt-{tag}.xlsx", h).json()["import_id"]
    assert _commit(iid, h).status_code == 200
    rows = [x for x in _cal_rows(tag) if str(x["date"]) == "2026-01-05"]
    assert rows and rows[0]["kind"] == "unknown"
    r = client.put("/leave/types", json={"code": code, "label": "Test Leave",
                                         "kind": "leave", "leave_group": "annual"},
                   headers=h)
    assert r.status_code == 200 and r.json()["code"] == code
    r = client.post("/leave/reprocess", headers=h)
    assert r.status_code == 200 and r.json()["updated"] >= 1
    rows = [x for x in _cal_rows(tag) if str(x["date"]) == "2026-01-05"]
    assert rows[0]["kind"] == "leave"
    r = client.put("/leave/types", json={"code": code, "kind": "bogus"}, headers=h)
    assert r.status_code == 422


def test_name_mismatch_warning_with_directory_employee():
    h, tag = _headers(), _tag()
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO employees (id, name, status) VALUES (%s, %s, 'active')",
                    (f"zt-{tag}-90001", "Someone Else"))
        conn.commit()
        cur.close()
    finally:
        conn.close()
    iid = _upload(_workbook_bytes([("Jan", _jan(tag=tag))]),
                  f"zt-{tag}.xlsx", h).json()["import_id"]
    codes = {i["code"] for i in
             client.get(f"/leave/imports/{iid}/issues", headers=h).json()["issues"]}
    assert "EMPLOYEE_NAME_MISMATCH" in codes


# --- janitor -----------------------------------------------------------------


def test_janitor_expires_and_fails_stuck():
    h = _headers()
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO leave_import (file_sha256, original_filename, status,"
                    " period_start, period_end, expires_at, uploaded_at)"
                    " VALUES ('zt-sha-exp', 'zt-exp.xlsx', 'preview_ready',"
                    " '2026-01-01', '2026-01-31', now() - interval '1 hour',"
                    " now() - interval '25 hours') RETURNING id")
    finally:
        pass
    exp_id = cur.fetchone()["id"]
    try:
        cur.execute("INSERT INTO leave_import_staging (import_id, sheet, employee_id,"
                    " date, raw_code, kind) VALUES (%s, 'Jan', 'zt-x', '2026-01-05', 'P',"
                    " 'working')", (exp_id,))
        cur.execute("INSERT INTO leave_import (file_sha256, original_filename, status,"
                    " uploaded_at) VALUES ('zt-sha-stuck', 'zt-stuck.xlsx', 'parsing',"
                    " now() - interval '1 hour')")
        conn.commit()
        cur.close()
    finally:
        conn.close()
    # any upload run triggers the janitor
    tag = _tag()
    r = _upload(_workbook_bytes([("Jan", _jan(tag=tag))]), f"zt-{tag}.xlsx", h)
    assert r.status_code == 200, r.text
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT status, preview_names FROM leave_import WHERE id = %s",
                    (exp_id,))
        row = cur.fetchone()
        assert row["status"] == "expired"
        cur.execute("SELECT COUNT(*) AS n FROM leave_import_staging WHERE import_id = %s",
                    (exp_id,))
        assert cur.fetchone()["n"] == 0
        cur.execute("SELECT status FROM leave_import WHERE original_filename = 'zt-stuck.xlsx'")
        assert cur.fetchone()["status"] == "failed"
        cur.execute("DELETE FROM leave_import WHERE original_filename IN"
                    " ('zt-exp.xlsx', 'zt-stuck.xlsx')")
        conn.commit()
        cur.close()
    finally:
        conn.close()
