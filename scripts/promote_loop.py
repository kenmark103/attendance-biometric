"""Promote COSEC staging rows into the dashboard tables, on a loop.

Runs scripts/promote_cosec_to_attendance.sql every PROMOTE_INTERVAL_SECONDS
so the dashboard reflects each device poll near-live. The SQL is idempotent
(ON CONFLICT DO NOTHING): only genuinely new (employee, date) pairs are
inserted; existing rows are never overwritten.

Env:
  DATABASE_URL              required (same value as the api service)
  PROMOTE_SQL_PATH          default /scripts/promote_cosec_to_attendance.sql
  PROMOTE_INTERVAL_SECONDS  default 300
"""

import os
import signal
import sys
import time

import psycopg2

SQL_PATH = os.environ.get(
    "PROMOTE_SQL_PATH", "/scripts/promote_cosec_to_attendance.sql"
)
INTERVAL = int(os.environ.get("PROMOTE_INTERVAL_SECONDS", "300"))
DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    print("DATABASE_URL is required", file=sys.stderr)
    sys.exit(2)

with open(SQL_PATH, encoding="utf-8") as f:
    PROMOTE_SQL = f.read()

_stop = False


def _handle_stop(signum, frame):
    global _stop
    _stop = True


signal.signal(signal.SIGTERM, _handle_stop)
signal.signal(signal.SIGINT, _handle_stop)


def promote_once() -> None:
    conn = psycopg2.connect(DATABASE_URL)
    try:
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(PROMOTE_SQL)  # DO block RAISEs NOTICE with the inserted count
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
    except Exception as exc:  # keep looping; a bad poll must not kill the service
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
