"""
Loads the existing flat data.json export into the full normalized schema.

Source row shape (confirmed from the actual file):
[employee_id, name, date, in_time, out_time, work_hours, overtime,
 late_in, early_out, present_flag, team, leave_type, has_leave_data, exemption_reason]

Run (host, requires psycopg2-binary):
    python scripts/load_data.py /path/to/data.json

Or via Docker, with no host pip install needed:
    docker compose run --rm loader
(loader service is defined in docker-compose.yml, mounts ./data and ./scripts)
"""
import json
import sys
import os

import psycopg2
from psycopg2.extras import execute_values

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://attendance:attendance@localhost:5434/attendance"
)


def parse_time(value):
    """Source times are 'HH:MM' strings or None."""
    return value if value else None


def clean_team_name(name):
    # Source has at least one trailing-space team name ("App Compat ").
    return name.strip() if name else "Unassigned"


def load(json_path):
    with open(json_path, "r", encoding="utf-8") as f:
        rows = json.load(f)

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # 1. Teams
    team_names = sorted({clean_team_name(r[10]) for r in rows})
    execute_values(
        cur,
        "INSERT INTO teams (name) VALUES %s ON CONFLICT (name) DO NOTHING",
        [(t,) for t in team_names],
    )
    cur.execute("SELECT id, name FROM teams")
    team_id_by_name = {name: tid for tid, name in cur.fetchall()}

    # 2. Employees — current_team_id is a best-effort default from this
    #    person's MOST RECENT row in the export. This is only a convenience
    #    snapshot; it is NOT what attendance_records.team_id uses (that's
    #    taken per-row, per the snapshot-not-join principle discussed).
    #    current_role / current_shift stay NULL — this source has no shift
    #    or role data; that arrives once Zoho's employee sync exists.
    latest_row_by_employee = {}
    for r in rows:
        emp_id, name, date = r[0], r[1], r[2]
        if emp_id not in latest_row_by_employee or date > latest_row_by_employee[emp_id][2]:
            latest_row_by_employee[emp_id] = r

    employee_rows = [
        (emp_id, r[1], team_id_by_name[clean_team_name(r[10])])
        for emp_id, r in latest_row_by_employee.items()
    ]
    execute_values(
        cur,
        """
        INSERT INTO employees (id, name, current_team_id) VALUES %s
        ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, current_team_id = EXCLUDED.current_team_id
        """,
        employee_rows,
    )

    # 3. Attendance records
    attendance_rows = []
    leave_rows = []
    failed = 0
    for r in rows:
        try:
            employee_id, name, date, in_time, out_time, work_hours, overtime, \
                late_in, early_out, present, team, leave_type, has_leave_data, \
                exemption_reason = r

            team_id = team_id_by_name[clean_team_name(team)]

            attendance_rows.append((
                employee_id, date, parse_time(in_time), parse_time(out_time),
                work_hours or 0, overtime or 0, bool(late_in), bool(early_out),
                bool(present), team_id, "migrated",
            ))

            # Leave is split into its own table now — only insert a row
            # when the source actually flagged one.
            if leave_type:
                leave_rows.append((employee_id, date, leave_type, "approved", "zoho"))

        except Exception as e:
            failed += 1
            print(f"Skipping malformed row {r}: {e}", file=sys.stderr)

    execute_values(
        cur,
        """
        INSERT INTO attendance_records
            (employee_id, date, check_in, check_out, work_hours, overtime_hours,
             late_in, early_out, present, team_id, source)
        VALUES %s
        ON CONFLICT (employee_id, date) DO UPDATE SET
            check_in = EXCLUDED.check_in, check_out = EXCLUDED.check_out,
            work_hours = EXCLUDED.work_hours, overtime_hours = EXCLUDED.overtime_hours,
            late_in = EXCLUDED.late_in, early_out = EXCLUDED.early_out,
            present = EXCLUDED.present, team_id = EXCLUDED.team_id
        """,
        attendance_rows,
    )

    if leave_rows:
        execute_values(
            cur,
            """
            INSERT INTO leave_records (employee_id, date, leave_type, status, source)
            VALUES %s ON CONFLICT (employee_id, date, leave_type) DO NOTHING
            """,
            leave_rows,
        )

    cur.execute(
        "INSERT INTO sync_log (source, records_processed, records_failed, status, notes) VALUES (%s, %s, %s, %s, %s)",
        ("json_migration", len(attendance_rows), failed, "complete", f"loaded from {json_path}"),
    )

    conn.commit()
    cur.close()
    conn.close()
    print(
        f"Loaded {len(attendance_rows)} attendance records, {len(leave_rows)} leave records "
        f"({failed} skipped) across {len(employee_rows)} employees and {len(team_names)} teams."
    )


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "data.json"
    load(path)
