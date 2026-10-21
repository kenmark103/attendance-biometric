"""Regression tests for the COSEC staging -> dashboard promotion boundary.

These tests need the compose PostgreSQL because the promotion script depends on
the core teams, employees, attendance_records, and sync_log tables.
"""

import os
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

pytestmark = pytest.mark.db

ROOT = Path(__file__).resolve().parents[3]
PROMOTION_SQL = ROOT / "scripts" / "promote_cosec_to_attendance.sql"


def _engine():
    url = os.environ.get(
        "DATABASE_URL",
        "postgresql://attendance:attendance@localhost:5434/attendance",
    )
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    return create_engine(url)


@pytest.fixture()
def engine():
    eng = _engine()
    tag = "zt-promote"
    try:
        with eng.begin() as conn:
            conn.execute(text("DELETE FROM attendance_records WHERE employee_id LIKE :prefix"),
                         {"prefix": f"{tag}%"})
            conn.execute(text("DELETE FROM employees WHERE id LIKE :prefix"),
                         {"prefix": f"{tag}%"})
            conn.execute(text("DELETE FROM cosec_attendance_daily WHERE user_id LIKE :prefix"),
                         {"prefix": f"{tag}%"})
            conn.execute(text("DELETE FROM cosec_users WHERE user_id LIKE :prefix"),
                         {"prefix": f"{tag}%"})
            conn.execute(text("DELETE FROM teams WHERE name LIKE :prefix"),
                         {"prefix": f"{tag}%"})
    except OperationalError as exc:
        eng.dispose()
        pytest.skip(f"compose PostgreSQL unavailable: {exc}")
    yield eng
    with eng.begin() as conn:
        conn.execute(text("DELETE FROM attendance_records WHERE employee_id LIKE :prefix"),
                     {"prefix": f"{tag}%"})
        conn.execute(text("DELETE FROM employees WHERE id LIKE :prefix"),
                     {"prefix": f"{tag}%"})
        conn.execute(text("DELETE FROM cosec_attendance_daily WHERE user_id LIKE :prefix"),
                     {"prefix": f"{tag}%"})
        conn.execute(text("DELETE FROM cosec_users WHERE user_id LIKE :prefix"),
                     {"prefix": f"{tag}%"})
        conn.execute(text("DELETE FROM teams WHERE name LIKE :prefix"),
                     {"prefix": f"{tag}%"})
    eng.dispose()


def _run_promotion(engine):
    with engine.begin() as conn:
        conn.execute(text(PROMOTION_SQL.read_text(encoding="utf-8")))


def test_promotion_maps_scope_and_updates_biometric_rows(engine):
    day = date(2026, 10, 20)
    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO cosec_users (user_id, user_name, in_scope, team)
                VALUES
                  ('zt-promote-1001', 'Promoted Person', TRUE, 'zt-promote-team'),
                  ('zt-promote-1002', 'Out of Scope', FALSE, 'zt-promote-team')
            """)
        )
        conn.execute(
            text("""
                INSERT INTO cosec_attendance_daily
                  (user_id, process_date, punch1, punch2, overtime_min,
                   work_time_min, is_processed, quality)
                VALUES
                  ('zt-promote-1001', :day,
                   '2026-10-20 08:03:00+03', '2026-10-20 17:10:00+03',
                   10, 547, TRUE, 'ok'),
                  ('zt-promote-1002', :day,
                   '2026-10-20 08:00:00+03', '2026-10-20 17:00:00+03',
                   0, 540, TRUE, 'ok')
            """),
            {"day": day},
        )

    _run_promotion(engine)

    with engine.connect() as conn:
        row = conn.execute(
            text("""
                SELECT a.employee_id, a.date, a.check_in, a.check_out,
                       a.work_hours, a.overtime_hours, a.late_in,
                       a.present, a.source, t.name AS team
                FROM attendance_records a
                LEFT JOIN teams t ON t.id = a.team_id
                WHERE a.employee_id = 'zt-promote-1001'
            """
            )
        ).mappings().one()
        assert row["date"] == day
        assert str(row["check_in"])[:5] == "08:03"
        assert str(row["check_out"])[:5] == "17:10"
        assert float(row["work_hours"]) == pytest.approx(547 / 60, abs=0.01)
        assert float(row["overtime_hours"]) == pytest.approx(10 / 60, abs=0.01)
        assert row["late_in"] is False
        assert row["present"] is True
        assert row["source"] == "biometric"
        assert row["team"] == "zt-promote-team"
        assert conn.execute(
            text("SELECT count(*) FROM attendance_records WHERE employee_id = 'zt-promote-1002'")
        ).scalar_one() == 0

    with engine.begin() as conn:
        conn.execute(
            text("""
                UPDATE cosec_attendance_daily
                SET punch2 = '2026-10-20 18:00:00+03', work_time_min = 597
                WHERE user_id = 'zt-promote-1001' AND process_date = :day
            """),
            {"day": day},
        )
    _run_promotion(engine)

    with engine.connect() as conn:
        assert str(conn.execute(
            text("SELECT check_out FROM attendance_records WHERE employee_id = 'zt-promote-1001' AND date = :day"),
            {"day": day},
        ).scalar_one())[:5] == "18:00"


def test_promotion_does_not_overwrite_migrated_rows(engine):
    day = date(2026, 10, 20)
    with engine.begin() as conn:
        team_id = conn.execute(
            text("INSERT INTO teams (name) VALUES ('zt-promote-migrated-team') RETURNING id")
        ).scalar_one()
        conn.execute(
            text("INSERT INTO employees (id, name) VALUES ('zt-promote-migrated', 'Migrated Person')")
        )
        conn.execute(
            text("""
                INSERT INTO attendance_records
                  (employee_id, date, check_in, check_out, work_hours,
                   team_id, source, raw_ref)
                VALUES ('zt-promote-migrated', :day, '07:00', '15:00', 8,
                        :team_id, 'migrated', 'fixture')
            """),
            {"day": day, "team_id": team_id},
        )
        conn.execute(
            text("""
                INSERT INTO cosec_users (user_id, user_name, in_scope, team)
                VALUES ('zt-promote-migrated', 'Device Name', TRUE, 'zt-promote-migrated-team')
            """)
        )
        conn.execute(
            text("""
                INSERT INTO cosec_attendance_daily
                  (user_id, process_date, punch1, punch2, work_time_min,
                   is_processed, quality)
                VALUES ('zt-promote-migrated', :day,
                        '2026-10-20 08:00:00+03', '2026-10-20 17:00:00+03',
                        540, TRUE, 'ok')
            """),
            {"day": day},
        )

    _run_promotion(engine)

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT check_in, check_out, work_hours, source, raw_ref "
                 "FROM attendance_records WHERE employee_id = 'zt-promote-migrated' AND date = :day"),
            {"day": day},
        ).mappings().one()
        assert str(row["check_in"])[:5] == "07:00"
        assert str(row["check_out"])[:5] == "15:00"
        assert float(row["work_hours"]) == 8
        assert row["source"] == "migrated"
        assert row["raw_ref"] == "fixture"
