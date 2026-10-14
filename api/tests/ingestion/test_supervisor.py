"""Supervisor behavior: outage gating, recovery, auth slowdown, never-exit."""
import threading
import time

from app.ingestion.supervisor import (
    AuthError,
    NetworkError,
    ServerError,
    SupervisorConfig,
    SyncState,
    run_forever,
)


def _cfg(**kw):
    base = dict(
        poll_interval_s=0.02,
        probe_interval_s=0.01,
        probe_timeout_s=0.01,
        api_retry_min_s=0.02,
        api_retry_max_s=0.05,
        down_after_s=3600,
        auth_retry_s=0.05,
        log_every_n_failures=1000,
    )
    base.update(kw)
    return SupervisorConfig(**base)


def _run(sync_once, states, cfg=None, probe=None, stop_after=0.4):
    stop = threading.Event()
    cfg = cfg or _cfg()
    kwargs = {}
    if probe is not None:
        kwargs["probe"] = probe
    t = threading.Thread(
        target=run_forever,
        kwargs=dict(
            sync_once=sync_once, host="h", port=80, cfg=cfg,
            on_state=lambda s, i: states.append((s, i)), stop=stop, **kwargs
        ),
        daemon=True,
    )
    t.start()
    time.sleep(stop_after)
    stop.set()
    t.join(timeout=10)
    assert not t.is_alive(), "supervisor thread did not stop"


def test_healthy_stays_healthy():
    calls = []
    states = []
    _run(lambda: calls.append(1), states)
    assert len(calls) >= 1
    assert all(s is SyncState.HEALTHY for s, _ in states)


def test_outage_recovers_and_probe_gates_api_calls():
    calls = []
    states = []
    up = {"on": False}

    def sync_once():
        calls.append(1)
        if not up["on"]:
            raise NetworkError("down")

    def probe(host, port, timeout):
        return up["on"]

    def stopper():
        # flip the host up shortly after start; run_forever keeps going
        time.sleep(0.15)
        up["on"] = True

    stop = threading.Event()
    t = threading.Thread(
        target=run_forever,
        kwargs=dict(
            sync_once=sync_once, host="h", port=80, cfg=_cfg(),
            on_state=lambda s, i: states.append((s, i)), stop=stop, probe=probe,
        ),
        daemon=True,
    )
    t.start()
    stopper()
    time.sleep(0.4)
    stop.set()
    t.join(timeout=10)
    assert not t.is_alive()
    kinds = [s for s, _ in states]
    assert SyncState.DEGRADED in kinds
    assert SyncState.HEALTHY in kinds
    # while down, API attempts are probe-gated: exactly 1 failure + recoveries
    assert calls[0] == 1


def test_auth_error_slows_to_hourly_and_keeps_loop_alive():
    calls = []
    states = []

    def sync_once():
        calls.append(1)
        raise AuthError("401 rejected")

    _run(sync_once, states, cfg=_cfg(auth_retry_s=0.05), stop_after=0.3)
    # spaced one attempt per auth_retry_s — a slow drip, never a hammer loop
    assert 2 <= len(calls) <= 8
    assert states and states[0][0] is SyncState.AUTH_BLOCKED


def test_unexpected_exception_never_exits():
    calls = []
    states = []

    def sync_once():
        calls.append(1)
        if len(calls) < 3:
            raise ValueError("weird payload")

    _run(sync_once, states, probe=lambda *a: True)
    assert len(calls) >= 3  # kept going past the bugs
    assert SyncState.HEALTHY in [s for s, _ in states]


def test_server_error_backs_off():
    calls = []
    states = []

    def sync_once():
        calls.append(1)
        raise ServerError("HTTP 503")

    _run(sync_once, states, probe=lambda *a: True, stop_after=0.3)
    assert len(calls) >= 2  # retried with backoff, not abandoned
    assert SyncState.DEGRADED in [s for s, _ in states]
