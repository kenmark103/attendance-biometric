"""Transactional attendance and leave write operations.

The HTTP router owns authentication and request validation. This module owns
the database transaction for each bulk operation so the same write behavior
can be reused by ingestion jobs without duplicating cursor/commit/rollback
logic.
"""
import logging

from psycopg2.extras import execute_values


log = logging.getLogger(__name__)

ALLOWED_SOURCES = {"biometric", "zoho_manual", "migrated"}
INSERT_CHUNK_SIZE = 500


def insert_attendance(conn, payload):
    if not payload.records:
        return {"inserted": 0, "teams_created": 0, "employees_upserted": 0}

    cur = conn.cursor()
    try:
        team_names = sorted({
            (record.team_name or "").strip()
            for record in payload.records
            if (record.team_name or "").strip()
        })
        execute_values(
            cur,
            "INSERT INTO teams (name) VALUES %s ON CONFLICT (name) DO NOTHING",
            [(name,) for name in team_names],
        )
        cur.execute("SELECT id, name FROM teams")
        team_id_by_name = {row["name"]: row["id"] for row in cur.fetchall()}

        employees = {(record.employee_id, record.employee_name)
                     for record in payload.records}
        execute_values(
            cur,
            """
            INSERT INTO employees (id, name) VALUES %s
            ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
            """,
            list(employees),
        )

        inserted = 0
        for i in range(0, len(payload.records), INSERT_CHUNK_SIZE):
            chunk = payload.records[i:i + INSERT_CHUNK_SIZE]
            values = [
                (
                    record.employee_id, record.date, record.check_in,
                    record.check_out, record.work_hours,
                    record.overtime_hours, record.late_in, record.early_out,
                    record.present,
                    team_id_by_name.get((record.team_name or "").strip()),
                    payload.source,
                )
                for record in chunk
            ]
            execute_values(
                cur,
                """
                INSERT INTO attendance_records
                    (employee_id, date, check_in, check_out, work_hours,
                     overtime_hours, late_in, early_out, present, team_id,
                     source)
                VALUES %s
                ON CONFLICT (employee_id, date) DO UPDATE SET
                    check_in = EXCLUDED.check_in,
                    check_out = EXCLUDED.check_out,
                    work_hours = EXCLUDED.work_hours,
                    overtime_hours = EXCLUDED.overtime_hours,
                    late_in = EXCLUDED.late_in,
                    early_out = EXCLUDED.early_out,
                    present = EXCLUDED.present,
                    team_id = EXCLUDED.team_id,
                    source = EXCLUDED.source
                """,
                values,
            )
            inserted += len(chunk)

        # Keep the employee snapshot aligned with the latest attendance row.
        cur.execute(
            """
            UPDATE employees e SET current_team_id = latest.team_id
            FROM (
                SELECT DISTINCT ON (employee_id) employee_id, team_id
                FROM attendance_records
                ORDER BY employee_id, date DESC
            ) AS latest
            WHERE e.id = latest.employee_id AND latest.team_id IS NOT NULL
            """
        )
        cur.execute(
            """
            INSERT INTO sync_log
                (source, records_processed, records_failed, status, notes)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                f"api_bulk_{payload.source}", inserted, 0, "complete",
                "via POST /attendance/bulk",
            ),
        )
        conn.commit()
        return {
            "inserted": inserted,
            "teams_created": len(team_names),
            "employees_upserted": len(employees),
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def insert_leave(conn, payload):
    if not payload.records:
        return {"inserted": 0}

    cur = conn.cursor()
    try:
        values = [
            (record.employee_id, record.date, record.leave_type,
             record.status, payload.source)
            for record in payload.records
        ]
        execute_values(
            cur,
            """
            INSERT INTO leave_records
                (employee_id, date, leave_type, status, source)
            VALUES %s ON CONFLICT (employee_id, date, leave_type) DO NOTHING
            """,
            values,
        )
        conn.commit()
        return {"inserted": len(values)}
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def update_attendance_teams(conn, payload):
    if not payload.records:
        return {"updated": 0, "skipped": 0}

    cur = conn.cursor()
    updated = 0
    skipped = 0
    try:
        cur.execute("SELECT id, name FROM teams")
        team_id_by_name = {
            row["name"].strip(): row["id"] for row in cur.fetchall()
        }
        log.debug("team lookup: %s", team_id_by_name)

        for record in payload.records:
            team_name = record.team_name.strip() if record.team_name else None
            if not team_name:
                skipped += 1
                continue

            team_id = team_id_by_name.get(team_name)
            if team_id is None:
                log.warning("team not found during bulk update: %s", team_name)
                skipped += 1
                continue

            cur.execute(
                """
                UPDATE attendance_records SET team_id = %s
                WHERE employee_id = %s AND date = %s
                """,
                (team_id, record.employee_id, record.date),
            )
            updated += cur.rowcount

        conn.commit()
        return {"updated": updated, "skipped": skipped}
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
