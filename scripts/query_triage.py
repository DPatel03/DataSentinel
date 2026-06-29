#!/usr/bin/env python3
"""Query Week 2 triage and repair history."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import psycopg2

from validation.config import load_env, timescaledb_dsn


def main() -> int:
    load_env()
    dsn = timescaledb_dsn()

    triage_sql = """
        SELECT failure_class, classifier_source, count(*) AS n,
               round(avg(confidence)::numeric, 2) AS avg_conf
        FROM triage_events
        WHERE time > now() - interval '24 hours'
        GROUP BY failure_class, classifier_source
        ORDER BY n DESC
    """
    repair_sql = """
        SELECT field_repaired, validation_passed, routed_to_repaired, count(*) AS n
        FROM repair_attempts
        WHERE time > now() - interval '24 hours'
        GROUP BY field_repaired, validation_passed, routed_to_repaired
        ORDER BY n DESC
    """

    try:
        with psycopg2.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(triage_sql)
                triage_rows = cur.fetchall()
                cur.execute(repair_sql)
                repair_rows = cur.fetchall()
    except psycopg2.Error as exc:
        print(f"Query failed: {exc}", file=sys.stderr)
        print("Run: python scripts/migrate_week2.py", file=sys.stderr)
        return 1

    print("=== Triage events (24h) ===")
    if not triage_rows:
        print("No triage events yet.")
    else:
        print(f"{'failure_class':<22} {'source':<12} {'count':<8} avg_conf")
        print("-" * 55)
        for row in triage_rows:
            print(f"{row[0]:<22} {row[1]:<12} {row[2]:<8} {row[3]}")

    print("\n=== Repair attempts (24h) ===")
    if not repair_rows:
        print("No repair attempts yet.")
    else:
        print(f"{'field':<20} {'valid':<8} {'routed':<8} count")
        print("-" * 48)
        for row in repair_rows:
            print(f"{(row[0] or '-'):<20} {str(row[1]):<8} {str(row[2]):<8} {row[3]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
