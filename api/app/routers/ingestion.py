"""On-demand sync: device poll + staging promotion in one admin call.

The poller/promoter loops cover the steady state every 5 minutes, but when
someone is staring at the dashboard waiting for today's check-outs, "within
10 minutes" feels broken. This endpoint runs the same two steps immediately
and reports what moved, so the Sync-now button has something truthful to say.

No new logic: it reuses poll_once (catch-up aware) and the promotion SQL
file (idempotent, migrated rows stay frozen).
"""
import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import create_engine

from app.core.deps import admin
from app.core.db import get_conn
from app.ingestion.config import _normalize_db_url, load_settings, ConfigError
from app.ingestion.scope import import_scope
from app.ingestion.service import poll_once

router = APIRouter(tags=["ingestion"])

PROMOTE_SQL_PATH = os.environ.get(
    "PROMOTE_SQL_PATH", "/scripts/promote_cosec_to_attendance.sql"
)
SCOPE_CSV_PATH = os.environ.get("SCOPE_CSV_PATH", "/data/engineering_scope.csv")


def _engine():
    return create_engine(
        _normalize_db_url(os.environ.get("DATABASE_URL", "")), pool_pre_ping=True
    )


@router.post("/ingestion/sync-now")
def sync_now(user=Depends(admin)):
    try:
        settings = load_settings()
    except ConfigError as exc:
        raise HTTPException(status_code=503, detail=f"ingestion not configured: {exc}")

    summary = poll_once(_engine(), settings)
    if summary.status == "failed":
        raise HTTPException(
            status_code=502,
            detail="device poll failed; see ingestion_runs for the failing range",
        )

    # Scope self-heal (same rule as the promoter loop): promotion only sees
    # in_scope users, so a wiped scope would silently promote nothing.
    engine = _engine()
    with engine.connect() as c:
        from sqlalchemy import text as _text
        scoped = c.execute(_text("SELECT count(*) FROM cosec_users WHERE in_scope")).scalar()
    scope_restored = False
    if scoped == 0:
        try:
            import_scope(engine, SCOPE_CSV_PATH, True)
            scope_restored = True
        except (SystemExit, OSError) as exc:
            print(f"sync-now: scope restore failed ({exc}); promoting anyway")

    try:
        with open(PROMOTE_SQL_PATH, encoding="utf-8") as f:
            promote_sql = f.read()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"promotion script unreadable: {exc}")

    conn = get_conn()
    conn.autocommit = True
    try:
        cur = conn.cursor()
        cur.execute(promote_sql)
        cur.execute(
            "SELECT records_processed FROM sync_log WHERE source = 'cosec_promotion'"
            " ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()
    promoted = row["records_processed"] if row else 0
    return {
        "poll": {
            "status": summary.status,
            "received": summary.received,
            "written": summary.written,
            "malformed": summary.malformed,
            "run_id": summary.run_id,
        },
        "promoted": promoted,
        "scope_restored": scope_restored,
    }
