#!/usr/bin/env python3
"""Apply database migrations for existing DataSentinel installations."""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from validation.config import load_env, timescaledb_dsn

SQL_FILE = ROOT / "infra" / "migrations.sql"


def main() -> int:
    load_env()
    sql = SQL_FILE.read_text()
    dsn = timescaledb_dsn()

    try:
        with psycopg2.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
    except psycopg2.Error as exc:
        print(f"Migration failed: {exc}", file=sys.stderr)
        print("Ensure TimescaleDB is running: docker compose up -d", file=sys.stderr)
        return 1

    print("Database migrations applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
