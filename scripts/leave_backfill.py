"""One-off LOCAL backfill: upload the real HR workbook, commit Jan-Sep only.

October is deliberately excluded so it can be used for a manual UI test
(upload + preview + commit through the browser).

Local only — never CI (the real report contains PII and is gitignored).
Runs inside the api container where /data and /scripts are mounted:

    docker compose exec -T api python /scripts/leave_backfill.py /data/Engineering.xls
"""
import hashlib
import sys
import uuid

sys.path.insert(0, "/app")

FILE = sys.argv[1] if len(sys.argv) > 1 else "/data/Engineering.xls"

from fastapi.testclient import TestClient  # noqa: E402

from app.auth.security import hash_password  # noqa: E402
from app.core.db import get_conn  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
conn = get_conn()

email = f"backfill-{uuid.uuid4().hex[:8]}@attendance.internal"
password = uuid.uuid4().hex
try:
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (email, display_name, role, auth_provider,"
        " password_hash, is_active, must_change_password)"
        " VALUES (%s,'backfill','admin','local',%s,TRUE,FALSE) RETURNING id",
        (email, hash_password(password)))
    conn.commit()
    cur.close()
finally:
    conn.close()

r = client.post("/auth/login", json={"email": email, "password": password})
assert r.status_code == 200, r.text
H = {"Authorization": f"Bearer {r.json()['access_token']}"}

with open(FILE, "rb") as f:
    data = f.read()
print(f"uploading {FILE} ({len(data)} bytes, sha={hashlib.sha256(data).hexdigest()[:12]})")

r = client.post("/leave/imports",
                files={"file": ("Engineering.xls", data, "application/octet-stream")},
                headers=H)
assert r.status_code == 200, r.text
prev = r.json()
iid = prev["import_id"]
print(f"import #{iid}: status={prev['status']}")

sheets = prev["sheets"]
assert len(sheets) == 10, f"expected 10 sheets, got {len(sheets)}"
assert all(not s["blocked"] for s in sheets), "all sheets should parse clean"
assert prev["counts"]["total"] == 48389, prev["counts"]
assert prev["counts"]["employees"] == 181, prev["counts"]
assert prev["coverage_through"] == "2026-10-14", prev["coverage_through"]
print("preview invariants OK: 10 sheets, 181 IDs, 48389 rows, through 2026-10-14")

keep = [s["sheet"] for s in sheets if s["end"] < "2026-10-01"]
dropped = [s["sheet"] for s in sheets if s["end"] >= "2026-10-01"]
print(f"committing {len(keep)} sheets {keep}; holding back {dropped} for manual test")
assert dropped, "expected to hold back October"

r = client.post(f"/leave/imports/{iid}/commit", json={"sheets": keep}, headers=H)
assert r.status_code == 200, r.text
res = r.json()
print(f"committed: {res['committed_rows']} rows, coverage {res['coverage_through']}")
assert res["coverage_through"] == "2026-09-30", res

conn = get_conn()
try:
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS n, COUNT(DISTINCT employee_id) AS ids FROM calendar_day")
    row = cur.fetchone()
    assert row["n"] == res["committed_rows"], dict(row)
    print(f"calendar_day: {row['n']} rows, {row['ids']} IDs")
    cur.execute("DELETE FROM users WHERE email = %s", (email,))
    conn.commit()
    cur.close()
finally:
    conn.close()
print("backfill complete; temp admin removed; October left for manual test")
