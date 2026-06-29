#!/usr/bin/env python3
"""Register Avro schemas in Confluent Schema Registry with BACKWARD compatibility."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from confluent_kafka.schema_registry import Schema, SchemaRegistryClient
from confluent_kafka.schema_registry.error import SchemaRegistryError

SCHEMAS_DIR = Path(__file__).resolve().parent / "schemas"
RAW_TOPIC = "taxi.rides.raw"
SUBJECT = f"{RAW_TOPIC}-value"


def load_avsc(path: Path) -> str:
    return json.dumps(json.loads(path.read_text()))


def reset_subject(client: SchemaRegistryClient, subject: str) -> None:
    try:
        versions = client.delete_subject(subject, permanent=True)
        print(f"Deleted subject {subject} (versions: {versions})")
    except SchemaRegistryError as exc:
        if "Subject not found" in str(exc) or "404" in str(exc):
            print(f"Subject {subject} not found — nothing to delete")
        else:
            raise


def register_schemas(registry_url: str, compatibility: str = "BACKWARD", reset: bool = False) -> None:
    client = SchemaRegistryClient({"url": registry_url})

    if reset:
        reset_subject(client, SUBJECT)

    v1_schema = load_avsc(SCHEMAS_DIR / "taxi-ride-v1.avsc")
    v2_schema = load_avsc(SCHEMAS_DIR / "taxi-ride-v2.avsc")

    client.set_compatibility(subject_name=SUBJECT, level=compatibility)
    print(f"Set compatibility for {SUBJECT} -> {compatibility}")

    v1_id = client.register_schema(SUBJECT, Schema(v1_schema, "AVRO"))
    print(f"Registered taxi-ride-v1 (schema id={v1_id})")

    v2_id = client.register_schema(SUBJECT, Schema(v2_schema, "AVRO"))
    print(f"Registered taxi-ride-v2 (schema id={v2_id})")

    latest = client.get_latest_version(SUBJECT)
    print(f"Latest schema version: {latest.version} (id={latest.schema_id})")


def main() -> int:
    parser = argparse.ArgumentParser(description="Register taxi Avro schemas")
    parser.add_argument(
        "--registry-url",
        default="http://localhost:8081",
        help="Schema Registry URL",
    )
    parser.add_argument(
        "--compatibility",
        default="BACKWARD",
        choices=["BACKWARD", "BACKWARD_TRANSITIVE", "FULL", "FULL_TRANSITIVE", "FORWARD", "NONE"],
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete existing subject before registering (use after schema changes)",
    )
    args = parser.parse_args()

    try:
        register_schemas(args.registry_url, args.compatibility, reset=args.reset)
    except SchemaRegistryError as exc:
        print(f"Schema registration failed: {exc}", file=sys.stderr)
        print("Try: python ingestion/register_schemas.py --reset", file=sys.stderr)
        return 1
    except TypeError as exc:
        print(f"Schema registration failed (API error): {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
