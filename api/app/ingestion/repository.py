"""Postgres writes for the COSEC ingestion worker.

Uses SQLAlchemy 2.x engine + text() statements. The engine is created once
in cli.py (from Settings.database_url, which config.py normalizes to an
explicit ``postgresql+psycopg2://`` URL so the repo keeps its single
``postgresql://`` pattern in .env/compose) and passed in here.
"""

from datetime import date

from sqlalchemy import text

from .parser import DailyRow
from .quality import classify, is_processed


def start_run(engine, mode: str, d_from: date, d_to: date) -> int:
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "INSERT INTO ingestion_runs (mode, range_from, range_to, status)"
                " VALUES (:mode, :f, :t, 'running') RETURNING id"
            ),
            {"mode": mode, "f": d_from, "t": d_to},
        ).one()
        return int(row[0])


def finish_run(
    engine,
    run_id: int,
    status: str,
    received: int | None,
    written: int | None,
    malformed: int | None,
    error: str | None,
) -> None:
    if error is not None:
        error = error[:500]
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE ingestion_runs SET finished_at = now(), status = :status,"
                " rows_received = :r, rows_written = :w,"
                " rows_malformed = :m, error = :e WHERE id = :id"
            ),
            {
                "status": status,
                "r": received,
                "w": written,
                "m": malformed,
                "e": error,
                "id": run_id,
            },
        )


_USERS_UPSERT = text(
    "INSERT INTO cosec_users (user_id, user_name)"
    " VALUES (:user_id, :user_name)"
    " ON CONFLICT (user_id) DO UPDATE"
    " SET user_name = EXCLUDED.user_name,"
    "     last_seen_at = now()"
)

_DAILY_UPSERT = text(
    "INSERT INTO cosec_attendance_daily"
    "    (user_id, process_date, punch1, punch2, working_shift,"
    "     late_in_min, early_out_min, overtime_min, work_time_min,"
    "     is_processed, quality)"
    " VALUES"
    "    (:user_id, :process_date, :punch1, :punch2, :working_shift,"
    "     :late_in_min, :early_out_min, :overtime_min, :work_time_min,"
    "     :is_processed, :quality)"
    " ON CONFLICT (user_id, process_date) DO UPDATE SET"
    "    punch1        = EXCLUDED.punch1,"
    "    punch2        = EXCLUDED.punch2,"
    "    working_shift = EXCLUDED.working_shift,"
    "    late_in_min   = EXCLUDED.late_in_min,"
    "    early_out_min = EXCLUDED.early_out_min,"
    "    overtime_min  = EXCLUDED.overtime_min,"
    "    work_time_min = EXCLUDED.work_time_min,"
    "    is_processed  = EXCLUDED.is_processed,"
    "    quality       = EXCLUDED.quality,"
    "    updated_at    = now()"
    " WHERE ("
    "    cosec_attendance_daily.punch1, cosec_attendance_daily.punch2,"
    "    cosec_attendance_daily.working_shift, cosec_attendance_daily.late_in_min,"
    "    cosec_attendance_daily.early_out_min, cosec_attendance_daily.overtime_min,"
    "    cosec_attendance_daily.work_time_min, cosec_attendance_daily.is_processed,"
    "    cosec_attendance_daily.quality"
    " ) IS DISTINCT FROM ("
    "    EXCLUDED.punch1, EXCLUDED.punch2, EXCLUDED.working_shift,"
    "    EXCLUDED.late_in_min, EXCLUDED.early_out_min, EXCLUDED.overtime_min,"
    "    EXCLUDED.work_time_min, EXCLUDED.is_processed, EXCLUDED.quality"
    " )"
)


def write_chunk(engine, items: list[tuple[DailyRow, str]]) -> int:
    """Upsert one chunk in a single transaction. Returns rows written."""
    if not items:
        return 0
    # Last name seen wins per user_id; never touches in_scope/team.
    users: dict[str, str] = {}
    for row, _quality in items:
        users[row.user_id] = row.user_name
    daily_params = [
        {
            "user_id": row.user_id,
            "process_date": row.process_date,
            "punch1": row.punch1,
            "punch2": row.punch2,
            "working_shift": row.working_shift,
            "late_in_min": row.late_in_min,
            "early_out_min": row.early_out_min,
            "overtime_min": row.overtime_min,
            "work_time_min": row.work_time_min,
            "is_processed": is_processed(row),
            "quality": quality,
        }
        for row, quality in items
    ]
    with engine.begin() as conn:
        conn.execute(
            _USERS_UPSERT,
            [{"user_id": uid, "user_name": name} for uid, name in users.items()],
        )
        result = conn.execute(_DAILY_UPSERT, daily_params)
        return result.rowcount
