#!/usr/bin/env python3
"""Generate the 300-record labeled eval dataset for DataSentinel."""

from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATASET_PATH = Path(__file__).resolve().parent / "full_dataset.json"

RULES = {
    "fare_amount_range": "fare_amount",
    "trip_distance_range": "trip_distance",
    "dropoff_after_pickup": "dropoff_datetime",
    "max_trip_speed_mph": "trip_distance",
    "avro_deserialization_failed": None,
    "pickup_datetime_not_null": "pickup_datetime",
    "schema_version_mismatch": "schema_version",
}

FAILURE_CLASSES = (
    "data_entry_error",
    "genuine_anomaly",
    "schema_drift",
    "upstream_bug",
    "known_edge_case",
)


def _base_record(schema: str = "v1") -> dict:
    pickup = datetime(2019, 3, 15, 8, 30, 0) + timedelta(minutes=random.randint(0, 5000))
    dropoff = pickup + timedelta(minutes=random.randint(5, 45))
    record = {
        "pickup_datetime": pickup.isoformat(),
        "dropoff_datetime": dropoff.isoformat(),
        "fare_amount": round(random.uniform(5.0, 45.0), 2),
        "trip_distance": round(random.uniform(0.5, 12.0), 2),
        "total_amount": round(random.uniform(8.0, 55.0), 2),
        "passenger_count": random.randint(1, 4),
        "schema_version": schema,
    }
    if schema == "v2":
        record["congestion_surcharge"] = round(random.uniform(0.0, 2.75), 2)
    return record


def _payload(record: dict | None, rule: str) -> dict:
    return {
        "record": record,
        "rule_violated": rule,
        "contract_version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "sample_good_records": [_base_record() for _ in range(3)],
    }


def _dirty_real_records(n: int = 150) -> list[dict]:
    """150 dirty records modeled on real NYC TLC failure patterns."""
    samples: list[dict] = []
    generators = [
        ("fare_amount_range", "data_entry_error", lambda r: {**r, "fare_amount": -abs(r["fare_amount"])}),
        ("dropoff_after_pickup", "data_entry_error", lambda r: {**r, "pickup_datetime": r["dropoff_datetime"], "dropoff_datetime": r["pickup_datetime"]}),
        ("fare_amount_range", "genuine_anomaly", lambda r: {**r, "fare_amount": 999.0}),
        ("trip_distance_range", "genuine_anomaly", lambda r: {**r, "trip_distance": 150.0}),
        ("max_trip_speed_mph", "genuine_anomaly", lambda r: {**r, "trip_distance": 80.0, "dropoff_datetime": (datetime.fromisoformat(r["pickup_datetime"]) + timedelta(minutes=2)).isoformat()}),
        ("avro_deserialization_failed", "schema_drift", lambda r: None),
        ("schema_version_mismatch", "schema_drift", lambda r: {**r, "schema_version": "v9", "congestion_surcharge": 2.5}),
        ("pickup_datetime_not_null", "upstream_bug", lambda r: {k: v for k, v in r.items() if k != "pickup_datetime"}),
        ("trip_distance_range", "known_edge_case", lambda r: {**r, "trip_distance": 0.0}),
    ]
    idx = 0
    while len(samples) < n:
        rule, expected, mutator = generators[idx % len(generators)]
        schema = "v2" if rule in ("schema_version_mismatch",) else random.choice(["v1", "v2"])
        base = _base_record(schema)
        record = mutator(base)
        samples.append({"payload": _payload(record, rule), "expected_class": expected, "category": "dirty_real"})
        idx += 1
    return samples


def _synthetic_edge_cases(n: int = 100) -> list[dict]:
    """100 synthetic edge cases."""
    samples: list[dict] = []
    cases = [
        ("max_trip_speed_mph", "genuine_anomaly", lambda: {**_base_record(), "trip_distance": 50.0, "dropoff_datetime": (datetime(2019, 1, 1, 8, 0) + timedelta(seconds=30)).isoformat(), "pickup_datetime": "2019-01-01T08:00:00"}),
        ("fare_amount_range", "genuine_anomaly", lambda: {**_base_record(), "fare_amount": 0.0}),
        ("dropoff_after_pickup", "data_entry_error", lambda: {**_base_record(), "pickup_datetime": "2030-01-01T08:00:00", "dropoff_datetime": "2019-01-01T08:00:00"}),
        ("trip_distance_range", "known_edge_case", lambda: {**_base_record("v2"), "trip_distance": 0.01}),
        ("fare_amount_range", "data_entry_error", lambda: {**_base_record(), "fare_amount": -0.01}),
        ("avro_deserialization_failed", "schema_drift", lambda: None),
        ("trip_distance_range", "genuine_anomaly", lambda: {**_base_record(), "trip_distance": 200.0}),
        ("pickup_datetime_not_null", "upstream_bug", lambda: {k: v for k, v in _base_record().items() if k != "pickup_datetime"}),
    ]
    idx = 0
    while len(samples) < n:
        rule, expected, builder = cases[idx % len(cases)]
        record = builder()
        samples.append({"payload": _payload(record, rule), "expected_class": expected, "category": "synthetic_edge"})
        idx += 1
    return samples


def _adversarial_records(n: int = 50) -> list[dict]:
    """50 adversarial records — ambiguous, clean-but-dirty-looking, fool-the-LLM."""
    samples: list[dict] = []
    # Clean records — classifier should NOT invent failures (hallucination bait)
    for _ in range(15):
        record = _base_record(random.choice(["v1", "v2"]))
        samples.append({
            "payload": _payload(record, "none_clean_record"),
            "expected_class": "clean",
            "category": "adversarial_clean",
            "adversarial_type": "hallucination_injection",
        })
    # Ambiguous — could be data_entry_error OR genuine_anomaly
    for _ in range(15):
        record = _base_record()
        record["fare_amount"] = 499.0  # high but not negative
        samples.append({
            "payload": _payload(record, "fare_amount_range"),
            "expected_class": "genuine_anomaly",
            "category": "adversarial_ambiguous",
            "adversarial_type": "ambiguous_class",
        })
    # Looks broken but is valid edge case
    for _ in range(10):
        record = _base_record("v2")
        record["trip_distance"] = 0.0
        samples.append({
            "payload": _payload(record, "trip_distance_range"),
            "expected_class": "known_edge_case",
            "category": "adversarial_edge",
            "adversarial_type": "looks_broken_valid",
        })
    # Plausible wrong repair bait
    for _ in range(10):
        record = _base_record()
        record["fare_amount"] = -5.0
        record["trip_distance"] = 0.1
        samples.append({
            "payload": _payload(record, "fare_amount_range"),
            "expected_class": "data_entry_error",
            "category": "adversarial_repair",
            "adversarial_type": "wrong_repair_bait",
            "expected_repair_field": "fare_amount",
            "expected_repaired_value": 5.0,
        })
    return samples[:n]


def generate_dataset(seed: int = 42) -> list[dict]:
    random.seed(seed)
    dataset = []
    dataset.extend(_dirty_real_records(150))
    dataset.extend(_synthetic_edge_cases(100))
    dataset.extend(_adversarial_records(50))
    return dataset


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate DataSentinel eval dataset")
    parser.add_argument("--output", type=Path, default=DATASET_PATH)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    dataset = generate_dataset(seed=args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(dataset, indent=2))
    print(f"Wrote {len(dataset)} records to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
