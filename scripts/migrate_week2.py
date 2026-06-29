#!/usr/bin/env python3
"""Apply Week 2 database migrations."""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from validation.config import load_env, timescaledb_dsn

SQL_FILE = ROOT / "infra" / "week2.sql"


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
        return 1

    print("Week 2 tables ready: triage_events, repair_attempts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
