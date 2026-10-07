import calendar
import logging
import signal
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import text

from .config import TZ, Settings
from .cosec_client import fetch_range
from .parser import PayloadError, parse_payload
from .quality import classify
from .repository import finish_run, start_run, write_chunk

log = logging.getLogger(__name__)


def chunk_ranges(d_from: date, d_to: date, max_days: int):
    cur = d_from
    while cur <= d_to:
        end = min(cur + timedelta(days=max_days - 1), d_to)
        yield cur, end
        cur = end + timedelta(days=1)


def poll_window(settings: Settings, now: datetime | None = None) -> tuple[date, date]:
    today = (now or datetime.now(TZ)).astimezone(TZ).date()
    return (today - timedelta(days=settings.poll_lookback_days), today)


@dataclass
class RunSummary:
    status: str
    received: int
    written: int
    malformed: int
    run_id: int | None


def ingest_range(engine, settings: Settings, mode: str, d_from: date, d_to: date) -> RunSummary:
    lock_conn = engine.connect()
    try:
        locked = lock_conn.execute(text("SELECT pg_try_advisory_lock(727001)")).scalar()
        lock_conn.commit()
        if not locked:
            log.info("another ingestion run is active; skipping")
            lock_conn.close()
            return RunSummary("skipped", 0, 0, 0, None)

        run_id = start_run(engine, mode, d_from, d_to)
        received = 0
        written = 0
        malformed = 0
        try:
            for a, b in chunk_ranges(d_from, d_to, settings.cosec_max_range_days):
                chunk_text = fetch_range(settings, a, b)
                result = parse_payload(chunk_text, TZ)
                if result.data_lines > 0 and result.malformed / result.data_lines > settings.max_malformed_ratio:
                    raise PayloadError(
                        f"too many malformed rows: {result.malformed}/{result.data_lines}"
                    )
                items = [(r, classify(r, settings.max_plausible_span_min)) for r in result.rows]
                written += write_chunk(engine, items)
                received += len(result.rows)
                malformed += result.malformed
                log.info(
                    "chunk %s..%s rows=%d malformed=%d duplicates=%d written=%d",
                    a, b, len(result.rows), result.malformed, result.duplicates, written,
                )
        except Exception as exc:
            finish_run(engine, run_id, "failed", received, written, malformed, f"{type(exc).__name__}: {exc}")
            log.exception("ingestion range %s..%s failed", d_from, d_to)
            return RunSummary("failed", received, written, malformed, run_id)
        finish_run(engine, run_id, "success", received, written, malformed, None)
        return RunSummary("success", received, written, malformed, run_id)
    finally:
        try:
            lock_conn.execute(text("SELECT pg_advisory_unlock(727001)"))
            lock_conn.commit()
        except Exception:
            pass
        finally:
            lock_conn.close()


def poll_once(engine, settings: Settings) -> RunSummary:
    d_from, d_to = poll_window(settings)
    return ingest_range(engine, settings, "poll", d_from, d_to)


_stop = False


def _handle_stop(signum, frame):
    global _stop
    _stop = True


def run_loop(engine, settings: Settings) -> None:
    global _stop
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    failures = 0
    while not _stop:
        try:
            summary = poll_once(engine, settings)
            if summary.status == "failed":
                failures += 1
            else:
                failures = 0
        except Exception:
            log.exception("poll_once raised")
            failures += 1
        if failures >= 5:
            log.error("ingestion unhealthy: 5 consecutive failures")
        for _ in range(settings.poll_interval_s):
            if _stop:
                break
            time.sleep(1)


LOCK_WAIT_S = 15
LOCK_WAIT_TRIES = 20  # 20 x 15s = 5 minutes of waiting for the poller to release the lock


def month_ranges(d_from: date, d_to: date):
    """Yield (start, end) per calendar month, inclusive, clipped to d_from..d_to."""
    cur = d_from
    while cur <= d_to:
        last_day = date(cur.year, cur.month, calendar.monthrange(cur.year, cur.month)[1])
        end = min(last_day, d_to)
        yield cur, end
        cur = end + timedelta(days=1)


def backfill_months(engine, settings: Settings, d_from: date, d_to: date, pause_s: int = 2) -> date | None:
    """Ingest d_from..d_to one calendar month at a time.

    Returns None on full success. On failure returns the start date of the month
    that failed, which is where the operator should restart with --from.
    Each month is its own ingestion_runs row, so progress is visible in the table.
    """
    ranges = list(month_ranges(d_from, d_to))
    total = len(ranges)
    for i, (a, b) in enumerate(ranges, start=1):
        summary = None
        for _ in range(LOCK_WAIT_TRIES):
            summary = ingest_range(engine, settings, "backfill", a, b)
            if summary.status != "skipped":
                break
            log.info("lock held by the poller; waiting %ds before retrying %s..%s", LOCK_WAIT_S, a, b)
            time.sleep(LOCK_WAIT_S)
        else:
            log.error("could not acquire the ingestion lock for %s..%s after %d tries", a, b, LOCK_WAIT_TRIES)
            return a
        log.info(
            "backfill %d/%d %s..%s status=%s received=%d written=%d malformed=%d",
            i, total, a, b, summary.status, summary.received, summary.written, summary.malformed,
        )
        if summary.status != "success":
            return a
        if i < total:
            time.sleep(pause_s)
    return None
