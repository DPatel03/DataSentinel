#!/usr/bin/env python3
"""Query pipeline status — breaches, triage, repairs, agents, prompts."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import psycopg2
from psycopg2.extras import RealDictCursor

from validation.config import load_env, timescaledb_dsn


def _print_section(cur: psycopg2.extensions.cursor, title: str, sql: str) -> None:
    print(f"\n=== {title} ===")
    cur.execute(sql)
    rows = cur.fetchall()
    if not rows:
        print("  (none)")
        return
    for row in rows:
        print(" ", dict(row))


def main() -> int:
    load_env()
    dsn = timescaledb_dsn()

    sections = {
        "Contract breaches (24h)": """
            SELECT rule_name, field_name, sum(failure_count) AS failures
            FROM contract_breaches
            WHERE time > now() - interval '24 hours'
            GROUP BY rule_name, field_name
            ORDER BY failures DESC
            LIMIT 10
        """,
        "Triage events (24h)": """
            SELECT failure_class, classifier_source, count(*) AS n,
                   round(avg(confidence)::numeric, 2) AS avg_conf
            FROM triage_events
            WHERE time > now() - interval '24 hours'
            GROUP BY failure_class, classifier_source
            ORDER BY n DESC
        """,
        "Repair attempts (24h)": """
            SELECT field_repaired, validation_passed, routed_to_repaired, count(*) AS n
            FROM repair_attempts
            WHERE time > now() - interval '24 hours'
            GROUP BY field_repaired, validation_passed, routed_to_repaired
            ORDER BY n DESC
        """,
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
        "LLM traces (recent)": """
            SELECT agent_name, model, latency_ms, cost_usd, success
            FROM llm_traces
            ORDER BY time DESC LIMIT 5
        """,
    }

    try:
        with psycopg2.connect(dsn) as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                for title, sql in sections.items():
                    _print_section(cur, title, sql)
    except psycopg2.Error as exc:
        print(f"Query failed: {exc}", file=sys.stderr)
        print("Run: python scripts/migrate.py", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
