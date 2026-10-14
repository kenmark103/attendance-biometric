"""
Resilient supervisor for the COSEC sync (adapted from a contributor script).

Goal: the sync loop NEVER exits because the network is down. When the cable is
unplugged it waits cheaply (a TCP probe, not API calls), and when the COSEC host
becomes reachable again it syncs — and poll_range() backfills from the last
success, so the outage days are covered without anyone re-running anything.

Wire-up (already done in service.run_loop):
    run_forever(sync_once, host=..., port=...,
                cfg=SupervisorConfig(poll_interval_s=...),
                on_state=..., stop=...)

Contract for `sync_once`:
    - fresh HTTP client per call (our cosec_client builds a new Session per
      fetch_range — no pooled keep-alive to go stale after a cable pull),
    - explicit timeouts (connect=5s, read=COSEC_TIMEOUT_SECONDS),
    - failures translated: connection/timeout -> NetworkError,
      HTTP 401/403 -> AuthError, HTTP 5xx -> ServerError.
      Anything else propagates; the supervisor logs it and keeps going.

`on_state(state, info)` persists healthy/degraded/down/auth_blocked for the
Data health tab. `restart: unless-stopped` + "Start Docker Desktop when you
sign in" covers host reboots.
"""
from __future__ import annotations

import logging
import random
import socket
import threading
from dataclasses import dataclass
from enum import Enum
from time import monotonic
from typing import Callable, Optional

log = logging.getLogger("sync.supervisor")


class SyncState(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"          # failing, for less than down_after_s
    DOWN = "down"                  # failing for down_after_s or longer
    AUTH_BLOCKED = "auth_blocked"  # credentials rejected, retrying very slowly


class NetworkError(Exception):
    """Connection refused, unreachable, DNS failure, timeout."""


class ServerError(Exception):
    """COSEC answered with HTTP 5xx."""


class AuthError(Exception):
    """COSEC answered 401/403. Do not hammer: risk of account lockout."""


@dataclass
class SupervisorConfig:
    poll_interval_s: int = 300      # normal cadence when healthy
    probe_interval_s: int = 30      # cheap TCP check while the host is unreachable
    probe_timeout_s: float = 3.0
    api_retry_min_s: int = 60       # first wait between failed API attempts
    api_retry_max_s: int = 600      # cap for the exponential backoff
    down_after_s: int = 3600        # label the outage DOWN after this long
    auth_retry_s: int = 3600        # one attempt per hour after a 401/403
    log_every_n_failures: int = 10  # avoid log spam during long outages


def tcp_probe(host: str, port: int, timeout: float) -> bool:
    """True if a TCP connection to host:port can be opened. No API call is made."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def run_forever(
    sync_once: Callable[[], None],
    host: str,
    port: int,
    cfg: Optional[SupervisorConfig] = None,
    on_state: Optional[Callable[[SyncState, dict], None]] = None,
    stop: Optional[threading.Event] = None,
    probe: Callable[[str, int, float], bool] = tcp_probe,
    clock: Callable[[], float] = monotonic,
) -> None:
    cfg = cfg or SupervisorConfig()
    stop = stop or threading.Event()
    notify = on_state or (lambda state, info: None)

    state = SyncState.HEALTHY
    failing_since: Optional[float] = None   # clock time of the first failure in this outage
    next_api_at = 0.0                       # earliest time for the next API attempt
    backoff = float(cfg.api_retry_min_s)
    failures = 0

    def set_state(new: SyncState, **info) -> None:
        nonlocal state
        if new is not state:
            log.warning("sync state %s -> %s %s", state.value, new.value, info or "")
            state = new
            notify(new, info)

    def outage_state(now: float) -> SyncState:
        assert failing_since is not None
        return SyncState.DOWN if now - failing_since >= cfg.down_after_s else SyncState.DEGRADED

    def record_failure(now: float, err: BaseException, trace: bool = False) -> None:
        nonlocal failing_since, failures, next_api_at, backoff
        if failing_since is None:
            failing_since = now
        failures += 1
        if failures == 1 or failures % cfg.log_every_n_failures == 0:
            if trace:
                log.exception("sync failed (attempt %d)", failures)
            else:
                log.warning("sync failed (attempt %d): %s", failures, err)
        # exponential backoff with jitter between real API attempts
        next_api_at = now + backoff * random.uniform(0.8, 1.2)
        backoff = min(backoff * 2, float(cfg.api_retry_max_s))
        set_state(outage_state(now), error=str(err))

    while not stop.is_set():
        now = clock()
        try:
            in_outage = failing_since is not None and state is not SyncState.AUTH_BLOCKED
            if in_outage:
                # Cheap check first: do not touch the API while the host is unreachable.
                if not probe(host, port, cfg.probe_timeout_s):
                    set_state(outage_state(now), error="host unreachable")
                    stop.wait(cfg.probe_interval_s)
                    continue
                if now < next_api_at:
                    stop.wait(min(cfg.probe_interval_s, next_api_at - now))
                    continue

            sync_once()

        except AuthError as err:
            if failing_since is None:
                failing_since = now
            log.error("sync rejected by COSEC (auth): %s. Next attempt in %ss", err, cfg.auth_retry_s)
            set_state(SyncState.AUTH_BLOCKED, error=str(err))
            stop.wait(cfg.auth_retry_s)
            continue

        except (NetworkError, ServerError, OSError) as err:
            record_failure(now, err)
            stop.wait(cfg.probe_interval_s)
            continue

        except Exception as err:  # bug or unexpected payload: log it, never exit
            record_failure(now, err, trace=True)
            stop.wait(cfg.probe_interval_s)
            continue

        else:
            outage_s = None if failing_since is None else clock() - failing_since
            failing_since = None
            failures = 0
            backoff = float(cfg.api_retry_min_s)
            next_api_at = 0.0
            if state is not SyncState.HEALTHY:
                log.info("sync recovered after %.0fs", outage_s or 0)
            set_state(SyncState.HEALTHY, downtime_s=outage_s)
            stop.wait(cfg.poll_interval_s)

    log.info("sync supervisor stopped")
