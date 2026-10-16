"""One-off LOCAL backfill: upload the real HR workbook, commit selected months.

By default commits every non-blocked sheet (October included — its last,
provisional column is excluded automatically). Pass --through YYYY-MM-DD to
hold back later sheets (e.g. keep October for a manual UI test):

    docker compose exec -T api python /scripts/leave_backfill.py /data/Engineering.xls
    docker compose exec -T api python /scripts/leave_backfill.py /data/Engineering.xls --through 2026-09-30

Local only — never CI (the real report contains PII and is gitignored).
Safe to re-run: an already-committed file is detected by hash and verified.
"""
import argparse
import hashlib
import sys
import uuid

sys.path.insert(0, "/app")

ap = argparse.ArgumentParser()
ap.add_argument("file", nargs="?", default="/data/Engineering.xls")
ap.add_argument("--through", default=None,
                help="Commit only sheets ending on or before this date (YYYY-MM-DD)")
args = ap.parse_args()
FILE = args.file

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
if prev.get("already_imported"):
    print(f"import #{iid}: already uploaded (status={prev['status']})")
    if prev["status"] == "committed":
        print("already committed; verifying counts and exiting")
    else:
        r = client.get(f"/leave/imports/{iid}", headers=H)
        assert r.status_code == 200, r.text
        prev = r.json()
        print(f"resuming {prev['status']} preview #{iid}")
else:
    print(f"import #{iid}: status={prev['status']}")

if prev.get("already_imported") and prev.get("status") == "committed":
    sheets = None  # nothing to preview; go straight to verification
else:
    sheets = prev["sheets"]
    assert len(sheets) == 10, f"expected 10 sheets, got {len(sheets)}"
    assert all(not s["blocked"] for s in sheets), "all sheets should parse clean"
    assert prev["counts"]["total"] == 48389, prev["counts"]
    assert prev["counts"]["employees"] == 181, prev["counts"]
    assert prev["coverage_through"] == "2026-10-14", prev["coverage_through"]
    print("preview invariants OK: 10 sheets, 181 IDs, 48389 rows, through 2026-10-14")

if sheets is None:
    print("nothing to commit; verifying stored state")
else:
    keep = [s["sheet"] for s in sheets
            if args.through is None or s["end"] <= args.through]
    dropped = [s["sheet"] for s in sheets if s["sheet"] not in keep]
    print(f"committing {len(keep)} sheets {keep}"
          + (f"; holding back {dropped} (--through {args.through})" if dropped else ""))
    assert keep, "selection is empty; check --through"
    r = client.post(f"/leave/imports/{iid}/commit", json={"sheets": keep}, headers=H)
    assert r.status_code == 200, r.text
    res = r.json()
    print(f"committed: {res['committed_rows']} rows, coverage {res['coverage_through']}")
    if args.through:
        assert res["coverage_through"] == args.through, res

conn = get_conn()
try:
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS n, COUNT(DISTINCT employee_id) AS ids FROM calendar_day")
    row = cur.fetchone()
    print(f"calendar_day: {row['n']} rows, {row['ids']} IDs")
    cur.execute("SELECT through_date FROM leave_coverage WHERE source = 'xls'")
    cov = cur.fetchone()
    print(f"leave coverage: {cov['through_date'] if cov else None}")
    cur.execute("DELETE FROM users WHERE email = %s", (email,))
    conn.commit()
    cur.close()
finally:
    conn.close()
print("backfill complete; temp admin removed")
