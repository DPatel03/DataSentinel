#!/usr/bin/env python3
"""Apply Week 3 database migrations."""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from validation.config import load_env, timescaledb_dsn

SQL_FILE = ROOT / "infra" / "week3.sql"


def main() -> int:
    load_env()
    try:
        with psycopg2.connect(timescaledb_dsn()) as conn:
            with conn.cursor() as cur:
                cur.execute(SQL_FILE.read_text())
            conn.commit()
    except psycopg2.Error as exc:
        print(f"Migration failed: {exc}", file=sys.stderr)
        return 1

    print("Week 3 tables ready: anomaly_patterns, anomaly_history, review_queue,")
    print("  schema_evolution_events, prompt_versions, prompt_eval_runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
