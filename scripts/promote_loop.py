"""Promote COSEC staging rows into the dashboard tables, on a loop.

Runs scripts/promote_cosec_to_attendance.sql every PROMOTE_INTERVAL_SECONDS
so the dashboard reflects each device poll near-live. The SQL is idempotent:
inserts are new-pairs-only and updates are limited to biometric-sourced rows,
so existing/migrated rows are never overwritten.

Two hard-won robustness rules live here:
1. The SQL file is re-read EVERY cycle (not once at startup), so editing the
   promotion logic takes effect without restarting this service.
2. Scope self-heal: promotion only sees in_scope users, and the scope flags
   have twice been found wiped (all false). If the scoped count is 0, the
   roster CSV is re-applied before promoting and the event is logged loudly.
   A non-zero scope is never touched.

Env:
  DATABASE_URL              required (same value as the api service)
  PROMOTE_SQL_PATH          default /scripts/promote_cosec_to_attendance.sql
  SCOPE_CSV_PATH            default /data/engineering_scope.csv
  PROMOTE_INTERVAL_SECONDS  default 300
"""

import os
import signal
import sys
import time

sys.path.insert(0, "/app")

import psycopg2
from sqlalchemy import create_engine, text

from app.ingestion.config import _normalize_db_url
from app.ingestion.scope import import_scope

SQL_PATH = os.environ.get(
    "PROMOTE_SQL_PATH", "/scripts/promote_cosec_to_attendance.sql"
)
CSV_PATH = os.environ.get("SCOPE_CSV_PATH", "/data/engineering_scope.csv")
INTERVAL = int(os.environ.get("PROMOTE_INTERVAL_SECONDS", "300"))
DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    print("DATABASE_URL is required", file=sys.stderr)
    sys.exit(2)

engine = create_engine(_normalize_db_url(DATABASE_URL), pool_pre_ping=True)

_stop = False


def _handle_stop(signum, frame):
    global _stop
    _stop = True


signal.signal(signal.SIGTERM, _handle_stop)
signal.signal(signal.SIGINT, _handle_stop)


def scoped_count() -> int:
    conn = psycopg2.connect(DATABASE_URL)
    try:
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM cosec_users WHERE in_scope")
        n = cur.fetchone()[0]
        cur.close()
        return n
    finally:
        conn.close()


def promote_once() -> None:
    if scoped_count() == 0:
        print("SCOPE WIPED (0 in_scope users) — re-applying roster before promoting", flush=True)
        try:
            import_scope(engine, CSV_PATH, True)
        except SystemExit as exc:
            print(f"scope restore refused (exit {exc.code}); promoting anyway", flush=True)
        except OSError as exc:
            print(f"scope CSV unreadable ({exc}); promoting anyway", flush=True)
    with open(SQL_PATH, encoding="utf-8") as f:
        promote_sql = f.read()
    conn = psycopg2.connect(DATABASE_URL)
    try:
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(promote_sql)  # DO block RAISEs NOTICE with the affected count
        for notice in list(conn.notices):
            print(notice.strip(), flush=True)
        del conn.notices[:]
        cur.close()
    finally:
        conn.close()


failures = 0
while not _stop:
    try:
        promote_once()
        failures = 0
        print(f"promote ok; next run in {INTERVAL}s", flush=True)
    except Exception as exc:  # keep looping; a bad cycle must not kill the service
        failures += 1
        print(
            f"promote failed ({failures} consecutive): "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
            flush=True,
        )
    for _ in range(INTERVAL):
        if _stop:
            break
        time.sleep(1)

print("promoter stopping")
