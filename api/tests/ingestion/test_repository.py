"""DB-backed ingestion tests. Needs the compose Postgres.

Run:  DATABASE_URL=postgresql://attendance:attendance@localhost:5434/attendance \
      pytest api/tests/ingestion/test_repository.py -m db

ISOLATION: cosec_users / cosec_attendance_daily / ingestion_runs are LIVE
tables — the ingestor writes real device rows into them every poll and the
promoter reads them. This suite therefore NEVER blanket-deletes from them:
it only touches the reserved IDs in _TEST_IDS (see _purge_test_rows). A
blanket DELETE here wipes the real biometric staging data and silently
stops the promoter from promoting anything.
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

# Reserved IDs for this suite. Two carry the `zt-` prefix the other suites
# use, so they can never collide with a device employee number. The third is
# numeric with leading zeros — the zt- convention cannot express a leading
# zero, which is exactly what the round-trip test needs to prove.
_TEST_IDS = ("zt-20001", "zt-20002", "zt-20003", "00090001")
# Team the scope-preservation test marks in_scope with.
_TEST_TEAM = "zt-test-team"
# Names this suite writes. A reserved ID carrying any other name is REAL
# device data, and the fixture refuses to touch it.
_TEST_NAMES = {"Alpha", "Beta", "Gamma", "Alpha Renamed"}

H = "UserID|UserName|ProcessDate|Punch1|Punch2|WorkingShift|LateIn|EarlyOut|Overtime|WorkTime"
_HERE = os.path.dirname(os.path.abspath(__file__))
_MIGRATION_CANDIDATES = [
    os.path.abspath(os.path.join(_HERE, "..", "..", "..", "db", "migrations", "003_cosec_ingestion.sql")),
    "/app/db/migrations/003_cosec_ingestion.sql",  # container with ./db mounted at /app/db
]
MIGRATION = next((p for p in _MIGRATION_CANDIDATES if os.path.exists(p)),
                 _MIGRATION_CANDIDATES[0])


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
    _purge_test_rows(eng)
    yield eng
    _purge_test_rows(eng)
    eng.dispose()


def _purge_test_rows(eng):
    """Delete ONLY this suite's reserved rows.

    Never `DELETE FROM cosec_users` / `cosec_attendance_daily` /
    `ingestion_runs`: those tables hold the real device feed. Wiping them
    stops promotion and destroys the biometric staging history.

    The promoter loop runs every 5 minutes and promotes any in_scope
    staging row into the dashboard tables. This suite marks a test user
    in_scope, so the promoter can pick it up mid-test — purge the
    dashboard tables too, for the reserved IDs only.
    """
    with eng.begin() as conn:
        # Real device rows must never be mistaken for test rows.
        rows = conn.execute(
            text("SELECT user_id, user_name FROM cosec_users")
        ).fetchall()
        for user_id, user_name in rows:
            if user_id in _TEST_IDS and user_name not in _TEST_NAMES:
                raise AssertionError(
                    f"reserved test id {user_id!r} holds real device data "
                    f"(user_name={user_name!r}); refusing to delete it"
                )
        ids = list(_TEST_IDS)
        conn.execute(
            text("DELETE FROM attendance_records WHERE employee_id = ANY(:ids)"),
            {"ids": ids},
        )
        conn.execute(
            text("DELETE FROM employees WHERE id = ANY(:ids)"), {"ids": ids}
        )
        conn.execute(
            text("DELETE FROM teams WHERE name = :t AND NOT EXISTS"
                 " (SELECT 1 FROM employees e WHERE e.current_team_id = teams.id)"),
            {"t": _TEST_TEAM},
        )
        conn.execute(
            text("DELETE FROM cosec_attendance_daily WHERE user_id = ANY(:ids)"),
            {"ids": ids},
        )
        conn.execute(
            text("DELETE FROM cosec_users WHERE user_id = ANY(:ids)"), {"ids": ids}
        )
        # ingestion_runs is an append-only audit log of real polls: never
        # deleted. The lock test only compares counts before/after.


def _items(*lines):
    res = parse_payload(H + "\n" + "\n".join(lines), TZ)
    assert res.malformed == 0
    return [(r, classify(r, 960)) for r in res.rows]


def L10(*fields: str) -> str:
    assert len(fields) == 10
    return "|".join(fields)


def test_write_chunk_idempotent_and_update(engine):
    items = _items(
        L10("zt-20001", "Alpha", "02/10/2026", "02/10/2026 09:20:16", "02/10/2026 16:39:27", "AL", "0", "0", "0", "439"),
        L10("zt-20002", "Beta", "02/10/2026", "02/10/2026 09:00:00", "02/10/2026 17:00:00", "AL", "0", "0", "0", "480"),
        L10("zt-20003", "Gamma", "02/10/2026", "", "", "", "", "", "", ""),
    )
    assert write_chunk(engine, items) == 3
    assert write_chunk(engine, items) == 0  # unchanged rows untouched
    with engine.connect() as conn:
        before = conn.execute(
            text("SELECT updated_at FROM cosec_attendance_daily WHERE user_id='zt-20001'")
        ).scalar_one()
    changed = _items(
        L10("zt-20001", "Alpha", "02/10/2026", "02/10/2026 09:20:16", "02/10/2026 18:39:27", "AL", "0", "0", "0", "559"),
        L10("zt-20002", "Beta", "02/10/2026", "02/10/2026 09:00:00", "02/10/2026 17:00:00", "AL", "0", "0", "0", "480"),
        L10("zt-20003", "Gamma", "02/10/2026", "", "", "", "", "", "", ""),
    )
    assert write_chunk(engine, changed) == 1
    with engine.connect() as conn:
        after = conn.execute(
            text("SELECT updated_at FROM cosec_attendance_daily WHERE user_id='zt-20001'")
        ).scalar_one()
        assert after >= before


def test_write_chunk_preserves_scope_and_team(engine):
    items = _items(L10("zt-20001", "Alpha", "02/10/2026", "02/10/2026 09:20:16", "02/10/2026 16:39:27", "AL", "0", "0", "0", "439"))
    write_chunk(engine, items)
    with engine.begin() as conn:
        conn.execute(text("UPDATE cosec_users SET in_scope=true, team=:t WHERE user_id='zt-20001'"), {"t": _TEST_TEAM})
    renamed = _items(L10("zt-20001", "Alpha Renamed", "02/10/2026", "02/10/2026 09:20:16", "02/10/2026 16:39:27", "AL", "0", "0", "0", "439"))
    write_chunk(engine, renamed)
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT user_name, in_scope, team FROM cosec_users WHERE user_id='zt-20001'")
        ).mappings().one()
        assert row["user_name"] == "Alpha Renamed"
        assert row["in_scope"] is True and row["team"] == _TEST_TEAM


def test_user_id_leading_zeros_round_trip(engine):
    write_chunk(engine, _items(L10("00090001", "Gamma", "02/10/2026", "", "", "", "", "", "", "")))
    with engine.connect() as conn:
        assert conn.execute(text("SELECT user_id FROM cosec_users WHERE user_id='00090001'")).scalar_one() == "00090001"


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
