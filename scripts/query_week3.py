#!/usr/bin/env python3
"""Query Week 3 review queue, anomalies, schema evolution, prompts."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import psycopg2
from psycopg2.extras import RealDictCursor

from validation.config import load_env, timescaledb_dsn


def main() -> int:
    load_env()
    dsn = timescaledb_dsn()

    queries = {
        "Review queue (open)": """
            SELECT id, record_key, failure_class, confidence, rule_violated, summary
            FROM review_queue WHERE status = 'open'
            ORDER BY created_at DESC LIMIT 10
        """,
        "Schema evolution events": """
            SELECT detected_schema_version, confidence, registry_updated, github_issue_url
            FROM schema_evolution_events
            WHERE time > now() - interval '24 hours'
            ORDER BY time DESC LIMIT 10
        """,
        "Anomaly history": """
            SELECT record_key, pattern_name, severity, rule_violated
            FROM anomaly_history
            WHERE time > now() - interval '24 hours'
            ORDER BY time DESC LIMIT 10
        """,
        "Active prompts": """
            SELECT agent_name, prompt_id, version, accuracy, is_active
            FROM prompt_versions WHERE is_active = TRUE
            ORDER BY agent_name
        """,
    }

    try:
        with psycopg2.connect(dsn) as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                for title, sql in queries.items():
                    print(f"\n=== {title} ===")
                    cur.execute(sql)
                    rows = cur.fetchall()
                    if not rows:
                        print("  (none)")
                    for row in rows:
                        print(" ", dict(row))
    except psycopg2.Error as exc:
        print(f"Query failed: {exc}", file=sys.stderr)
        print("Run: python scripts/migrate_week3.py", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
