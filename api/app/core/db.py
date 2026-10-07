"""Shared DB connection (raw psycopg2, matching the rest of the api)."""
import psycopg2
import psycopg2.extras

from app.core import settings


def get_conn():
    return psycopg2.connect(
        settings.DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor
    )
