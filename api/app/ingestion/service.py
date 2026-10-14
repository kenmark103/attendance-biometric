import calendar
import logging
import signal
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy import text

from .config import TZ, Settings
from .cosec_client import fetch_range
from .parser import PayloadError, parse_payload
from .quality import classify
from .repository import finish_run, start_run, write_chunk
from .supervisor import (
    AuthError,
    NetworkError,
    ServerError,
    SupervisorConfig,
    SyncState,
    run_forever,
)

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


def last_success_end(engine) -> date | None:
    """End of the most recent successfully ingested range (poll or backfill)."""
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT max(range_to) FROM ingestion_runs"
                " WHERE status = 'success' AND mode IN ('poll', 'backfill')"
            )
        ).first()
    return row[0] if row and row[0] else None


def poll_range(settings: Settings, today: date, prev_end: date | None) -> tuple[date, date]:
    """Poll window, extended backwards to cover an outage gap.

    After a long stop (PC asleep for days), the plain 3-day lookback would
    silently skip days. Extending from the day after the last success makes
    the first poll after a gap self-healing. Capped so one poll never pulls
    more than COSEC_MAX_RANGE_DAYS; anything older needs a manual backfill.
    """
    d_from = today - timedelta(days=settings.poll_lookback_days)
    d_to = today
    if prev_end is not None:
        d_from = min(d_from, prev_end + timedelta(days=1))
        earliest = d_to - timedelta(days=settings.cosec_max_range_days - 1)
        if d_from < earliest:
            log.warning(
                "outage gap exceeds %sd (last success %s); catching up from %s only,"
                " run a backfill for the older range",
                settings.cosec_max_range_days, prev_end, earliest,
            )
            d_from = earliest
    return d_from, d_to


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
    today = datetime.now(TZ).astimezone(TZ).date()
    prev_end = last_success_end(engine)
    d_from, d_to = poll_range(settings, today, prev_end)
    if d_from > d_to:
        log.info("poll window empty (last success %s is in the future); skipping", prev_end)
        return RunSummary("skipped", 0, 0, 0, None)
    if prev_end is not None and d_from < today - timedelta(days=settings.poll_lookback_days):
        log.info("catch-up poll %s..%s after outage (last success %s)", d_from, d_to, prev_end)
    return ingest_range(engine, settings, "poll", d_from, d_to)


def device_host_port(settings: Settings) -> tuple[str, int]:
    """Host/port for the cheap TCP probe. Unparsable URL -> probe disabled."""
    try:
        u = urlparse(settings.cosec_base_url)
        if not u.hostname:
            return "", 80
        return u.hostname, u.port or (443 if u.scheme == "https" else 80)
    except Exception:
        return "", 80


def _run_error(engine, run_id: int | None) -> str:
    if run_id is None:
        return "poll failed"
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT error FROM ingestion_runs WHERE id = :id"), {"id": run_id}
        ).first()
    return (row[0] if row and row[0] else None) or "poll failed"


def _classify_error(err_text: str) -> Exception:
    # ingestion_runs.error is formatted as f"{type(exc).__name__}: {exc}",
    # so these prefixes are exact, not heuristics over free text.
    if "CosecAuthError" in err_text:
        return AuthError(err_text)
    if "CosecHttpError: HTTP 5" in err_text:
        return ServerError(err_text)
    if "CosecError" in err_text or "ConnectionError" in err_text or "Timeout" in err_text:
        return NetworkError(err_text)
    return Exception(err_text)


def make_sync_once(engine, settings: Settings):
    """Adapt poll_once to the supervisor contract (raise on failure)."""
    def sync_once() -> None:
        summary = poll_once(engine, settings)
        if summary.status == "failed":
            raise _classify_error(_run_error(engine, summary.run_id))
        # "skipped" (lock held by a parallel run) is not a failure.
    return sync_once


def make_on_state(engine, service: str = "ingestor"):
    """Persist supervisor state changes for the Data health tab."""
    def on_state(state: SyncState, info: dict) -> None:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO sync_state (service, state, since, last_error, updated_at)"
                    " VALUES (:service, :state, now(), :err, now())"
                    " ON CONFLICT (service) DO UPDATE SET state = EXCLUDED.state,"
                    " since = CASE WHEN sync_state.state <> EXCLUDED.state"
                    " THEN now() ELSE sync_state.since END,"
                    " last_error = EXCLUDED.last_error, updated_at = now()"
                ),
                {"service": service, "state": state.value,
                 "err": info.get("error") if isinstance(info, dict) else None},
            )
    return on_state


def run_loop(engine, settings: Settings) -> None:
    """Supervised poll loop: never exits on device/network failure.

    Cable pull -> cheap TCP probes + backoff (no API hammering, no log spam)
    -> automatic sync on replug, with poll_range() backfilling the outage days.
    Auth rejection -> one attempt per hour (no lockout risk).
    State changes land in sync_state for the Data health tab.
    """
    stop = threading.Event()

    def _handle(signum, frame):
        stop.set()

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)
    host, port = device_host_port(settings)
    cfg = SupervisorConfig(
        poll_interval_s=settings.poll_interval_s,
        probe_interval_s=min(30, settings.poll_interval_s),
    )
    on_state = make_on_state(engine)
    on_state(SyncState.HEALTHY, {})  # ensure the row exists even before any transition
    # Unparsable device URL: probing is meaningless, always attempt the API.
    extra = {} if host else {"probe": lambda *a: True}
    run_forever(
        make_sync_once(engine, settings),
        host=host or "127.0.0.1",
        port=port,
        cfg=cfg,
        on_state=on_state,
        stop=stop,
        **extra,
    )


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
