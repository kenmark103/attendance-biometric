"""Shared DB connection (raw psycopg2, matching the rest of the api).

Ownership rule: one connection per request, opened here and closed here.
Endpoints declare ``conn=Depends(get_db)`` and never call ``get_conn()``
or ``close()`` themselves — they only use the cursor and commit/rollback
their own work. FastAPI evaluates ``get_db`` once per request and shares
the yielded connection across nested dependencies (e.g. auth + handler),
so a request still uses exactly one connection.
"""
import psycopg2
import psycopg2.extras

from app.core import settings


def get_conn():
    return psycopg2.connect(
        settings.DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor
    )


def get_db():
    """FastAPI dependency: yield a request-scoped connection, always closed."""
    conn = get_conn()
    try:
        yield conn
    finally:
        conn.close()
