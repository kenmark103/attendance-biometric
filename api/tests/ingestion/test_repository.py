"""DB-backed ingestion tests. Needs the compose Postgres.

Run:  DATABASE_URL=postgresql://attendance:attendance@localhost:5434/attendance \
      pytest api/tests/ingestion/test_repository.py -m db
"""

import os
from datetime import date

import pytest
from sqlalchemy import create_engine, text

from app.ingestion.config import TZ
from app.ingestion.parser import parse_payload
from app.ingestion.quality import classify
from app.ingestion.repository import write_chunk
from app.ingestion.service import ingest_range

pytestmark = pytest.mark.db

H = "UserID|UserName|ProcessDate|Punch1|Punch2|WorkingShift|LateIn|EarlyOut|Overtime|WorkTime"
MIGRATION = os.path.join(os.path.dirname(__file__), "..", "..", "..", "db", "migrations", "003_cosec_ingestion.sql")


def _engine():
    url = os.environ.get("DATABASE_URL", "postgresql://attendance:attendance@localhost:5434/attendance")
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    return create_engine(url)


@pytest.fixture()
def engine():
    eng = _engine()
    with open(os.path.abspath(MIGRATION), encoding="utf-8") as f:
        sql = f.read()
    with eng.begin() as conn:
        for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
            conn.execute(text(stmt))
        conn.execute(text("DELETE FROM cosec_attendance_daily"))
        conn.execute(text("DELETE FROM cosec_users"))
        conn.execute(text("DELETE FROM ingestion_runs"))
    yield eng
    eng.dispose()


def _items(*lines):
    res = parse_payload(H + "\n" + "\n".join(lines), TZ)
    assert res.malformed == 0
    return [(r, classify(r, 960)) for r in res.rows]


def L10(*fields: str) -> str:
    assert len(fields) == 10
    return "|".join(fields)


def test_write_chunk_idempotent_and_update(engine):
    items = _items(
        L10("20001", "Alpha", "02/10/2026", "02/10/2026 09:20:16", "02/10/2026 16:39:27", "AL", "0", "0", "0", "439"),
        L10("20002", "Beta", "02/10/2026", "02/10/2026 09:00:00", "02/10/2026 17:00:00", "AL", "0", "0", "0", "480"),
        L10("0001", "Gamma", "02/10/2026", "", "", "", "", "", "", ""),
    )
    assert write_chunk(engine, items) == 3
    assert write_chunk(engine, items) == 0  # unchanged rows untouched
    with engine.connect() as conn:
        before = conn.execute(
            text("SELECT updated_at FROM cosec_attendance_daily WHERE user_id='20001'")
        ).scalar_one()
    changed = _items(
        L10("20001", "Alpha", "02/10/2026", "02/10/2026 09:20:16", "02/10/2026 18:39:27", "AL", "0", "0", "0", "559"),
        L10("20002", "Beta", "02/10/2026", "02/10/2026 09:00:00", "02/10/2026 17:00:00", "AL", "0", "0", "0", "480"),
        L10("0001", "Gamma", "02/10/2026", "", "", "", "", "", "", ""),
    )
    assert write_chunk(engine, changed) == 1
    with engine.connect() as conn:
        after = conn.execute(
            text("SELECT updated_at FROM cosec_attendance_daily WHERE user_id='20001'")
        ).scalar_one()
        assert after >= before


def test_write_chunk_preserves_scope_and_team(engine):
    items = _items(L10("20001", "Alpha", "02/10/2026", "02/10/2026 09:20:16", "02/10/2026 16:39:27", "AL", "0", "0", "0", "439"))
    write_chunk(engine, items)
    with engine.begin() as conn:
        conn.execute(text("UPDATE cosec_users SET in_scope=true, team='X' WHERE user_id='20001'"))
    renamed = _items(L10("20001", "Alpha Renamed", "02/10/2026", "02/10/2026 09:20:16", "02/10/2026 16:39:27", "AL", "0", "0", "0", "439"))
    write_chunk(engine, renamed)
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT user_name, in_scope, team FROM cosec_users WHERE user_id='20001'")
        ).mappings().one()
        assert row["user_name"] == "Alpha Renamed"
        assert row["in_scope"] is True and row["team"] == "X"


def test_user_id_leading_zeros_round_trip(engine):
    write_chunk(engine, _items(L10("0001", "Gamma", "02/10/2026", "", "", "", "", "", "", "")))
    with engine.connect() as conn:
        assert conn.execute(text("SELECT user_id FROM cosec_users WHERE user_id='0001'")).scalar_one() == "0001"


def test_ingest_range_skipped_when_locked(engine):
    from app.ingestion.config import Settings

    holder = engine.connect()
    assert holder.execute(text("SELECT pg_try_advisory_lock(727001)")).scalar() is True
    try:
        with engine.connect() as conn:
            n_before = conn.execute(text("SELECT count(*) FROM ingestion_runs")).scalar_one()
        from unittest.mock import patch

        settings = Settings("http://h", "u", "p", "", 60, 31, 300, 3, 960, 0.05)
        with patch("app.ingestion.service.fetch_range") as fr:
            summary = ingest_range(engine, settings, "poll", date(2026, 10, 1), date(2026, 10, 2))
        assert summary.status == "skipped" and summary.run_id is None
        fr.assert_not_called()
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM ingestion_runs")).scalar_one() == n_before
    finally:
        holder.execute(text("SELECT pg_advisory_unlock(727001)"))
        holder.commit()
        holder.close()
