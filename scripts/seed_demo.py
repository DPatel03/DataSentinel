#!/usr/bin/env python3
"""Seed TimescaleDB with a known-interesting demo so the dashboard is never empty."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ingestion.keys import ride_key
from validation.config import load_env, timescaledb_dsn

DEMO_PREFIX = "demo|"
NOW = datetime.now(timezone.utc)


def _good(**overrides) -> dict:
    record = {
        "vendor_id": 1,
        "pickup_datetime": "2019-01-01T08:00:00",
        "dropoff_datetime": "2019-01-01T08:18:00",
        "fare_amount": 14.5,
        "trip_distance": 2.4,
        "total_amount": 17.3,
        "passenger_count": 1,
        "pulocation_id": 161,
        "dolocation_id": 237,
        "schema_version": "v1",
    }
    record.update(overrides)
    return record


def _cases() -> list[dict]:
    fare = _good(pickup_datetime="2019-01-01T08:30:00", fare_amount=-14.5, total_amount=17.3)
    fare_fixed = {**fare, "fare_amount": 14.5}
    distance = _good(
        pickup_datetime="2019-01-01T09:10:00",
        dropoff_datetime="2019-01-01T09:28:00",
        pulocation_id=50,
        dolocation_id=80,
        trip_distance=150.0,
        fare_amount=48.0,
        total_amount=55.0,
    )
    swapped = _good(
        pickup_datetime="2019-01-01T10:00:00",
        dropoff_datetime="2019-01-01T09:40:00",
        vendor_id=2,
        pulocation_id=12,
        dolocation_id=200,
    )
    swapped_fixed = {
        **swapped,
        "pickup_datetime": "2019-01-01T09:40:00",
        "dropoff_datetime": "2019-01-01T10:00:00",
    }
    zero = _good(
        pickup_datetime="2019-01-01T11:00:00",
        dropoff_datetime="2019-01-01T11:18:00",
        pulocation_id=1,
        dolocation_id=1,
        trip_distance=0.0,
        fare_amount=2.5,
        total_amount=3.8,
    )
    return [
        {
            "record": fare,
            "repaired": fare_fixed,
            "rule": "fare_amount_range",
            "field": "fare_amount",
            "failure_class": "data_entry_error",
            "explanation": "Negative fare is a sign-entry error.",
            "review": False,
            "repair": True,
        },
        {
            "record": distance,
            "repaired": None,
            "rule": "trip_distance_range",
            "field": "trip_distance",
            "failure_class": "genuine_anomaly",
            "explanation": "Trip distance exceeds plausible NYC taxi range.",
            "review": True,
            "repair": False,
        },
        {
            "record": swapped,
            "repaired": swapped_fixed,
            "rule": "dropoff_after_pickup",
            "field": "dropoff_datetime",
            "failure_class": "data_entry_error",
            "explanation": "Dropoff occurs before pickup — likely swapped timestamps.",
            "review": False,
            "repair": True,
        },
        {
            "record": zero,
            "repaired": None,
            "rule": "trip_distance_range",
            "field": "trip_distance",
            "failure_class": "known_edge_case",
            "explanation": "Zero-distance trip — known cancel / meter-reset pattern.",
            "review": True,
            "repair": False,
        },
    ]


def seed(dsn: str) -> int:
    cases = _cases()
    goods = [
        _good(pickup_datetime="2019-01-01T07:00:00", pulocation_id=90, dolocation_id=91),
        _good(pickup_datetime="2019-01-01T07:12:00", pulocation_id=100, dolocation_id=101, fare_amount=9.5),
        _good(pickup_datetime="2019-01-01T07:24:00", vendor_id=2, pulocation_id=140, dolocation_id=141),
    ]
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM contract_breaches WHERE record_key LIKE %s OR record_key IS NULL", (f"{DEMO_PREFIX}%",))
            cur.execute("DELETE FROM validation_events WHERE record_key LIKE %s", (f"{DEMO_PREFIX}%",))
            cur.execute("DELETE FROM triage_events WHERE record_key LIKE %s", (f"{DEMO_PREFIX}%",))
            cur.execute("DELETE FROM repair_attempts WHERE record_key LIKE %s", (f"{DEMO_PREFIX}%",))
            cur.execute("DELETE FROM review_queue WHERE record_key LIKE %s", (f"{DEMO_PREFIX}%",))
            cur.execute("DELETE FROM llm_traces WHERE trace_id LIKE %s", ("demo-%",))

            # 196 valid + 4 invalid = 2.0% — at the contract budget, not a breach.
            for i in range(196):
                cur.execute(
                    """
                    INSERT INTO validation_events (time, is_valid, latency_ms, rule_name, record_key)
                    VALUES (%s, TRUE, %s, NULL, %s)
                    """,
                    (NOW - timedelta(minutes=90 - i), 4.0 + (i % 7), f"{DEMO_PREFIX}ok|{i}"),
                )
            for i, case in enumerate(cases):
                key = f"{DEMO_PREFIX}{ride_key(case['record'])}"
                t = NOW - timedelta(minutes=20 - i)
                cur.execute(
                    """
                    INSERT INTO validation_events (time, is_valid, latency_ms, rule_name, record_key)
                    VALUES (%s, FALSE, %s, %s, %s)
                    """,
                    (t, 8.0 + i, case["rule"], key),
                )
                cur.execute(
                    """
                    INSERT INTO contract_breaches
                        (time, rule_name, field_name, contract_version, failure_count, sample_record, record_key)
                    VALUES (%s, %s, %s, '1.0.0', 1, %s::jsonb, %s)
                    """,
                    (t, case["rule"], case["field"], json.dumps(case["record"]), key),
                )
                payload = {
                    "record": case["record"],
                    "rule_violated": case["rule"],
                    "contract_version": "1.0.0",
                    "timestamp": t.isoformat(),
                    "sample_good_records": goods,
                }
                cur.execute(
                    """
                    INSERT INTO triage_events (
                        time, record_key, rule_violated, failure_class, confidence,
                        explanation, affected_field, requires_human_review,
                        classifier_source, raw_payload
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'heuristic', %s::jsonb)
                    """,
                    (
                        t,
                        key,
                        case["rule"],
                        case["failure_class"],
                        0.88 if case["repair"] else 0.74,
                        case["explanation"],
                        case["field"],
                        case["review"],
                        json.dumps(payload),
                    ),
                )
                if case["repair"] and case["repaired"]:
                    cur.execute(
                        """
                        INSERT INTO repair_attempts (
                            time, record_key, original_record, repaired_record,
                            field_repaired, confidence, validation_passed, routed_to_repaired
                        ) VALUES (%s, %s, %s::jsonb, %s::jsonb, %s, 0.9, TRUE, TRUE)
                        """,
                        (t, key, json.dumps(case["record"]), json.dumps(case["repaired"]), case["field"]),
                    )
                if case["review"]:
                    cur.execute(
                        """
                        INSERT INTO review_queue (
                            created_at, record_key, failure_class, confidence, rule_violated,
                            summary, recommended_action, status, record_payload, classification_payload
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'open', %s::jsonb, %s::jsonb)
                        """,
                        (
                            t,
                            key,
                            case["failure_class"],
                            0.74,
                            case["rule"],
                            case["explanation"],
                            "Review and accept or reject the classification.",
                            json.dumps(case["record"]),
                            json.dumps(
                                {
                                    "failure_class": case["failure_class"],
                                    "confidence": 0.74,
                                    "explanation": case["explanation"],
                                    "affected_field": case["field"],
                                    "source": "heuristic",
                                }
                            ),
                        ),
                    )
            cur.execute(
                """
                INSERT INTO llm_traces (
                    time, trace_id, agent_name, model, prompt_version,
                    input_tokens, output_tokens, latency_ms, cost_usd, success,
                    input_preview, output_preview
                ) VALUES (now(), 'demo-classifier-1', 'classifier', 'mock', 'v1',
                          120, 80, 18.0, 0.0, TRUE,
                          'demo DLQ: fare_amount_range', 'data_entry_error')
                """
            )
        conn.commit()
    return len(cases)


def main() -> int:
    load_env()
    dsn = timescaledb_dsn()
    try:
        n = seed(dsn)
    except psycopg2.Error as exc:
        print(f"Demo seed failed: {exc}", file=sys.stderr)
        print("Apply migrations first: python scripts/migrate.py", file=sys.stderr)
        return 1
    print(f"Seeded {n} dirty demo records + valid traffic (failure rate at the 2% SLA budget).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
