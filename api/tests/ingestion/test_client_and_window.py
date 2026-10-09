from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import requests

import app.ingestion.service as service
from app.ingestion.config import Settings
from app.ingestion.cosec_client import CosecAuthError, build_url, fetch_range
from app.ingestion.service import backfill_months, chunk_ranges, month_ranges, poll_range, poll_window


def _settings(**kw) -> Settings:
    base = dict(
        cosec_base_url="http://h/COSEC/api.svc/v2",
        cosec_user="u",
        cosec_password="p",
        database_url="postgresql+psycopg2://u:p@localhost:5432/db",
        cosec_timeout_s=60,
        cosec_max_range_days=31,
        poll_interval_s=300,
        poll_lookback_days=3,
        max_plausible_span_min=960,
        max_malformed_ratio=0.05,
    )
    base.update(kw)
    return Settings(**base)


def test_build_url_format():
    assert build_url("http://h/COSEC/api.svc/v2", date(2026, 10, 1), date(2026, 10, 6)) == \
        "http://h/COSEC/api.svc/v2/attendance-daily?action=get;date-range=01102026-06102026"


def test_semicolon_survives_request_preparation():
    url = build_url("http://h/COSEC/api.svc/v2", date(2026, 10, 1), date(2026, 10, 6))
    assert requests.Request("GET", url).prepare().url == url


def test_chunk_ranges_cover_without_gaps():
    chunks = list(chunk_ranges(date(2026, 6, 1), date(2026, 10, 6), 31))
    assert chunks[0][0] == date(2026, 6, 1)
    assert chunks[-1][1] == date(2026, 10, 6)
    assert all((b - a).days + 1 <= 31 for a, b in chunks)
    for ( _a1, b1), (a2, _b2) in zip(chunks, chunks[1:]):
        assert (a2 - b1).days == 1


def test_poll_window_uses_nairobi_not_utc():
    now = datetime(2026, 10, 6, 22, 30, tzinfo=timezone.utc)  # already Oct 7 in Nairobi
    assert poll_window(_settings(), now) == (date(2026, 10, 4), date(2026, 10, 7))


class _FakeResp:
    def __init__(self, status=None, body="", exc=None):
        self.status_code = status
        self.content = body.encode()
        self.exc = exc


def _mock_session_class(responses):
    """Build a Session class whose instance records calls and replays responses."""
    calls = {"n": 0}

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, timeout=None):
            calls["n"] += 1
            r = responses[min(calls["n"] - 1, len(responses) - 1)]
            if r.exc:
                raise r.exc
            return r

    return FakeSession, calls


def test_fetch_range_auth_error_no_retry():
    FakeSession, calls = _mock_session_class([_FakeResp(status=401)])
    with patch("app.ingestion.cosec_client.requests.Session", return_value=FakeSession()), \
         patch("app.ingestion.cosec_client.time.sleep") as slp:
        try:
            fetch_range(_settings(), date(2026, 10, 1), date(2026, 10, 2))
        except CosecAuthError:
            pass
        else:
            raise AssertionError("expected CosecAuthError")
        assert calls["n"] == 1
        slp.assert_not_called()


def test_fetch_range_retries_then_succeeds():
    FakeSession, calls = _mock_session_class(
        [_FakeResp(status=503), _FakeResp(status=503), _FakeResp(status=200, body="ok")]
    )
    with patch("app.ingestion.cosec_client.requests.Session", return_value=FakeSession()), \
         patch("app.ingestion.cosec_client.time.sleep"):
        assert fetch_range(_settings(), date(2026, 10, 1), date(2026, 10, 2)) == "ok"
        assert calls["n"] == 3


def test_fetch_range_rejects_inverted_range():
    try:
        fetch_range(_settings(), date(2026, 10, 2), date(2026, 10, 1))
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")


def test_month_ranges_full_year():
    ranges = list(month_ranges(date(2026, 1, 1), date(2026, 10, 6)))
    assert len(ranges) == 10
    assert ranges[0] == (date(2026, 1, 1), date(2026, 1, 31))
    assert ranges[1] == (date(2026, 2, 1), date(2026, 2, 28))
    assert ranges[-1] == (date(2026, 10, 1), date(2026, 10, 6))
    for (_, prev_end), (cur_start, _) in zip(ranges, ranges[1:]):
        assert (cur_start - prev_end).days == 1


def test_month_ranges_partial_and_edge_cases():
    assert list(month_ranges(date(2026, 1, 15), date(2026, 2, 10))) == [
        (date(2026, 1, 15), date(2026, 1, 31)),
        (date(2026, 2, 1), date(2026, 2, 10)),
    ]
    assert list(month_ranges(date(2026, 5, 5), date(2026, 5, 5))) == [(date(2026, 5, 5), date(2026, 5, 5))]
    feb28 = list(month_ranges(date(2028, 2, 1), date(2028, 2, 29)))
    assert feb28 == [(date(2028, 2, 1), date(2028, 2, 29))]


def _summary(status):
    return service.RunSummary(status, 1, 1, 0, 7)


def test_backfill_all_success():
    seen = []

    def fake_ingest(engine, settings, mode, a, b):
        seen.append((a, b))
        return _summary("success")

    with patch.object(service, "ingest_range", side_effect=fake_ingest), \
         patch.object(service.time, "sleep"):
        assert backfill_months(None, _settings(), date(2026, 1, 1), date(2026, 3, 15)) is None
        assert seen == [
            (date(2026, 1, 1), date(2026, 1, 31)),
            (date(2026, 2, 1), date(2026, 2, 28)),
            (date(2026, 3, 1), date(2026, 3, 15)),
        ]


def test_backfill_skipped_then_success_sleeps_lock_wait():
    calls = {"n": 0}

    def fake_ingest(engine, settings, mode, a, b):
        calls["n"] += 1
        return _summary("skipped" if calls["n"] <= 2 else "success")

    with patch.object(service, "ingest_range", side_effect=fake_ingest), \
         patch.object(service.time, "sleep") as slp:
        assert backfill_months(None, _settings(), date(2026, 1, 1), date(2026, 1, 31)) is None
        lock_waits = [c for c in slp.call_args_list if c.args and c.args[0] == service.LOCK_WAIT_S]
        assert len(lock_waits) == 2


def test_backfill_failed_returns_month_start():
    def fake_ingest(engine, settings, mode, a, b):
        if a == date(2026, 3, 1):
            return _summary("failed")
        return _summary("success")

    seen = []
    orig = fake_ingest

    def tracking(engine, settings, mode, a, b):
        seen.append(a)
        return orig(engine, settings, mode, a, b)

    with patch.object(service, "ingest_range", side_effect=tracking), \
         patch.object(service.time, "sleep"):
        assert backfill_months(None, _settings(), date(2026, 1, 1), date(2026, 4, 30)) == date(2026, 3, 1)
        assert date(2026, 4, 1) not in seen


def test_backfill_lock_never_released():
    with patch.object(service, "ingest_range", return_value=_summary("skipped")), \
         patch.object(service.time, "sleep"):
        assert backfill_months(None, _settings(), date(2026, 1, 1), date(2026, 1, 31)) == date(2026, 1, 1)
        assert service.ingest_range.call_count == service.LOCK_WAIT_TRIES


def test_poll_range_no_history_uses_lookback():
    assert poll_range(_settings(), date(2026, 10, 9), None) == (date(2026, 10, 6), date(2026, 10, 9))


def test_poll_range_recent_history_unchanged():
    assert poll_range(_settings(), date(2026, 10, 9), date(2026, 10, 8)) == (date(2026, 10, 6), date(2026, 10, 9))


def test_poll_range_outage_extends_to_day_after_last_success():
    assert poll_range(_settings(), date(2026, 10, 9), date(2026, 10, 2)) == (date(2026, 10, 3), date(2026, 10, 9))


def test_poll_range_long_outage_caps_at_device_limit():
    a, b = poll_range(_settings(), date(2026, 10, 9), date(2026, 7, 1))
    assert b == date(2026, 10, 9)
    assert (b - a).days + 1 == 31
