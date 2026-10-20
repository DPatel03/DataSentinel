"""Database helpers for dashboard API."""

from __future__ import annotations

import logging

import psycopg2
from psycopg2.extras import RealDictCursor

from validation.config import timescaledb_dsn

logger = logging.getLogger(__name__)


def get_connection():
    return psycopg2.connect(timescaledb_dsn())


def fetch_all(query: str, params: tuple | None = None) -> list[dict]:
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params)
                return [dict(row) for row in cur.fetchall()]
    except psycopg2.Error as exc:
        logger.warning("Database query failed: %s", exc)
        return []


def fetch_one(query: str, params: tuple | None = None) -> dict | None:
    rows = fetch_all(query, params)
    return rows[0] if rows else None


def execute(query: str, params: tuple | None = None) -> int:
    """Run a write query. Returns rowcount, or 0 on error."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                count = cur.rowcount
            conn.commit()
            return count
    except psycopg2.Error as exc:
        logger.warning("Database execute failed: %s", exc)
        return 0
