"""Validate the minimum runtime schema expected by the application.

Used after a fresh database initialization in CI and during deployment checks.
It intentionally checks only application-owned tables and columns, so adding
an unrelated table does not make validation fail.
"""
import os
import sys

import psycopg2


EXPECTED = {
    "teams": {"id", "name"},
    "employees": {"id", "name", "current_team_id", "status"},
    "attendance_records": {
        "employee_id", "date", "check_in", "check_out", "work_hours",
        "present", "team_id", "source",
    },
    "leave_records": {"employee_id", "date", "leave_type", "status"},
    "users": {"id", "email", "role", "auth_provider", "is_active"},
    "refresh_tokens": {"token_hash", "expires_at", "family_id"},
    "leave_import": {"file_sha256", "status", "coverage_through"},
    "calendar_day": {"employee_id", "date", "kind", "fraction"},
    "cosec_users": {"user_id", "in_scope"},
    "cosec_attendance_daily": {"user_id", "process_date", "is_processed"},
    "ingestion_runs": {"mode", "range_from", "range_to", "status"},
    "sync_state": {"service", "state", "since", "updated_at"},
}


def validate(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
            """
        )
        actual = {}
        for table, column in cur.fetchall():
            actual.setdefault(table, set()).add(column)

    missing = {
        table: sorted(columns - actual.get(table, set()))
        for table, columns in EXPECTED.items()
        if table not in actual or columns - actual[table]
    }
    if missing:
        raise RuntimeError(f"schema validation failed: {missing}")


def main():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    conn = psycopg2.connect(database_url)
    try:
        validate(conn)
    finally:
        conn.close()
    print("schema validation passed")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
