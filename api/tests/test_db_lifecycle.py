"""get_db lifecycle tests: one connection per request, always closed.

Pure unit tests (fake connection) — no DB needed. The endpoint-level proof
that behaviour is unchanged is the existing API suite (auth + leave +
ingestion run every endpoint through TestClient).
"""
import pytest

from app.core import db


class FakeConn:
    def __init__(self):
        self.closed = False
        self.commits = 0
        self.rollbacks = 0

    def close(self):
        self.closed = True

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _run(gen):
    """Drive the get_db generator like FastAPI does (yield, then teardown)."""
    conn = next(gen)
    return conn, gen


def test_close_on_success(monkeypatch):
    fake = FakeConn()
    monkeypatch.setattr(db, "get_conn", lambda: fake)
    gen = db.get_db()
    conn, _ = _run(gen)
    assert conn is fake
    conn.commit()  # endpoint work happens between yield and teardown
    try:
        next(gen)
    except StopIteration:
        pass
    assert fake.closed is True
    assert fake.commits == 1


def test_close_on_exception(monkeypatch):
    fake = FakeConn()
    monkeypatch.setattr(db, "get_conn", lambda: fake)
    gen = db.get_db()
    conn, _ = _run(gen)
    with pytest.raises(RuntimeError):
        gen.throw(RuntimeError("boom"))
    assert fake.closed is True
    assert fake.rollbacks == 1
    assert conn is fake
