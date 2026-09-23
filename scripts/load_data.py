"""
Loads data.json by POSTing to the running API's bulk-ingestion endpoints
(/attendance/bulk, /leave/bulk) — NOT by connecting to Postgres directly.

Uses only the Python standard library (urllib, json) — no pip install
required at all. Run this straight on the host with any Python 3:

    python scripts/load_data.py /path/to/data.json

Assumes the api service is already up (docker compose up -d) and
reachable at http://localhost:8001 (or set API_URL / AUTH_TOKEN below).
"""
import json
import os
import sys
import urllib.error
import urllib.request

API_URL = os.environ.get("API_URL", "http://localhost:8001")
AUTH_TOKEN = os.environ.get("AUTH_TOKEN")  # only needed once AUTH_REQUIRED=true


def post_json(path, payload):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{API_URL}{path}", data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    if AUTH_TOKEN:
        req.add_header("Authorization", f"Bearer {AUTH_TOKEN}")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{path} -> HTTP {e.code}: {detail}") from None


def clean_team_name(name):
    return name.strip() if name else "Unassigned"


def load(json_path):
    with open(json_path, "r", encoding="utf-8") as f:
        rows = json.load(f)

    attendance_records = []
    leave_records = []
    skipped = 0

    for r in rows:
        try:
            employee_id, name, date, in_time, out_time, work_hours, overtime, \
                late_in, early_out, present, team, leave_type, has_leave_data, \
                exemption_reason = r

            attendance_records.append({
                "employee_id": employee_id,
                "employee_name": name,
                "date": date,
                "check_in": in_time,
                "check_out": out_time,
                "work_hours": work_hours or 0,
                "overtime_hours": overtime or 0,
                "late_in": bool(late_in),
                "early_out": bool(early_out),
                "present": bool(present),
                "team_name": clean_team_name(team),
            })

            if leave_type:
                leave_records.append({
                    "employee_id": employee_id,
                    "date": date,
                    "leave_type": leave_type,
                    "status": "approved",
                })
        except Exception as e:
            skipped += 1
            print(f"Skipping malformed row {r}: {e}", file=sys.stderr)

    print(f"Posting {len(attendance_records)} attendance records to {API_URL}/attendance/bulk ...")
    result = post_json("/attendance/bulk", {"source": "migrated", "records": attendance_records})
    print(f"  -> {result}")

    if leave_records:
        print(f"Posting {len(leave_records)} leave records to {API_URL}/leave/bulk ...")
        result = post_json("/leave/bulk", {"source": "zoho", "records": leave_records})
        print(f"  -> {result}")

    if skipped:
        print(f"{skipped} malformed rows skipped — see stderr above.")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "data.json"
    load(path)
