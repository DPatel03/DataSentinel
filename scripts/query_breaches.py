#!/usr/bin/env python3
"""Query contract breach history in TimescaleDB."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import psycopg2

from validation.config import load_env, timescaledb_dsn


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser(description="Query contract_breaches hypertable")
    parser.add_argument("--dsn", default=timescaledb_dsn())
    parser.add_argument("--hours", type=int, default=1)
    args = parser.parse_args()

    query = """
        SELECT rule_name, field_name, count(*) AS breach_count
        FROM contract_breaches
        WHERE time > now() - interval '%s hours'
        GROUP BY rule_name, field_name
        ORDER BY breach_count DESC
    """

    try:
        with psycopg2.connect(args.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(query, (args.hours,))
                rows = cur.fetchall()
    except psycopg2.OperationalError as exc:
        print(f"Database connection failed: {exc}", file=sys.stderr)
        print(
            "\nTips:\n"
            "  1. Is Docker running?  docker compose ps\n"
            "  2. Use the DataSentinel DB on port 5433 (not local Postgres on 5432)\n"
            "  3. Check TIMESCALEDB_DSN in .env\n"
            "  4. Test: docker compose exec timescaledb psql -U datasentinel -d datasentinel -c '\\dt'",
            file=sys.stderr,
        )
        return 1

    if not rows:
        print("No breaches found in the requested window.")
        print("(Run the Spark validator + producer first if you haven't yet.)")
        return 0

    print(f"{'rule_name':<30} {'field_name':<20} breach_count")
    print("-" * 62)
    for rule_name, field_name, count in rows:
        print(f"{rule_name:<30} {field_name or '-':<20} {count}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
