import json
import os
import sys
import urllib.error
import urllib.request


API_URL = os.environ.get("API_URL", "http://localhost:8001")
AUTH_TOKEN = os.environ.get("AUTH_TOKEN")


def post_json(path, payload):
    body = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        f"{API_URL}{path}",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )

    if AUTH_TOKEN:
        req.add_header("Authorization", f"Bearer {AUTH_TOKEN}")

    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))

    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"{path} -> HTTP {e.code}: {detail}"
        ) from None


def clean_team_name(name):
    return name.strip() if name else None


def load(json_path):
    with open(json_path, "r", encoding="utf-8") as f:
        rows = json.load(f)

    attendance_team_updates = []
    skipped = 0

    for r in rows:
        try:
            (
                employee_id,
                employee_name,
                date,
                in_time,
                out_time,
                work_hours,
                overtime,
                late_in,
                early_out,
                present,
                team,
                leave_type,
                has_leave_data,
                exemption_reason,
            ) = r

            team_name = clean_team_name(team)

            attendance_team_updates.append(
                {
                    "employee_id": employee_id,
                    "date": date,
                    "team_name": team_name,
                }
            )

        except Exception as e:
            skipped += 1
            print(
                f"Skipping malformed row {r}: {e}",
                file=sys.stderr,
            )

    print(
        f"Updating team_id for "
        f"{len(attendance_team_updates)} attendance records..."
    )

    print("First 5 team names:")
    for record in attendance_team_updates[:5]:
        print(record["team_name"])

    result = post_json(
        "/attendance/bulk/team",
        {
            "records": attendance_team_updates,
        },
    )

    print(f"  -> {result}")

    if skipped:
        print(
            f"{skipped} malformed rows skipped.",
            file=sys.stderr,
            
        )


if __name__ == "__main__":
    path = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "data.json"
    )

    load(path)