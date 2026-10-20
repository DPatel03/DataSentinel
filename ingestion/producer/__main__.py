#!/usr/bin/env python3
"""Replay NYC TLC Parquet files to Kafka with time compression."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import pyarrow.parquet as pq
from confluent_kafka import Producer
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.avro import AvroSerializer
from confluent_kafka.serialization import SerializationContext, MessageField

from ingestion.keys import ride_key
from ingestion.producer.mapper import infer_schema_version, parquet_row_to_avro

SCHEMAS_DIR = Path(__file__).resolve().parents[1] / "schemas"
RAW_TOPIC = "taxi.rides.raw"


def load_schema_text(version: str) -> str:
    path = SCHEMAS_DIR / f"taxi-ride-{version}.avsc"
    return json.dumps(json.loads(path.read_text()))


def parse_pickup_datetime(value: str) -> datetime:
    if not value:
        return datetime.min
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def delivery_report(err, msg) -> None:
    if err is not None:
        print(f"Delivery failed: {err}", file=sys.stderr)


def run(
    file_path: Path,
    bootstrap_servers: str,
    registry_url: str,
    schema_version: str | None,
    compression_factor: float,
    max_records: int | None,
) -> None:
    table = pq.read_table(file_path)
    rows = table.to_pylist()

    rows.sort(key=lambda r: _row_get_pickup(r))

    first_version = schema_version or infer_schema_version(rows[0] if rows else {})
    schema_text = load_schema_text(first_version)

    registry = SchemaRegistryClient({"url": registry_url})
    serializer = AvroSerializer(registry, schema_text)

    producer = Producer({"bootstrap.servers": bootstrap_servers, "client.id": "taxi-producer"})

    sent = 0
    prev_pickup: datetime | None = None

    for row in rows:
        record = parquet_row_to_avro(row, schema_version=schema_version)
        version = record["schema_version"]

        if version != first_version:
            first_version = version
            schema_text = load_schema_text(version)
            serializer = AvroSerializer(registry, schema_text)

        payload = serializer(
            record,
            SerializationContext(RAW_TOPIC, MessageField.VALUE),
        )

        pickup = parse_pickup_datetime(record["pickup_datetime"])
        if prev_pickup is not None and compression_factor > 0:
            delta_seconds = max((pickup - prev_pickup).total_seconds(), 0)
            time.sleep(delta_seconds / compression_factor)

        producer.produce(
            topic=RAW_TOPIC,
            key=ride_key(record).encode("utf-8"),
            value=payload,
            on_delivery=delivery_report,
        )
        producer.poll(0)

        prev_pickup = pickup
        sent += 1

        if sent % 500 == 0:
            print(f"Published {sent} records...")
        if max_records and sent >= max_records:
            break

    producer.flush()
    print(f"Done. Published {sent} records to {RAW_TOPIC}.")


def _row_get_pickup(row: dict) -> datetime:
    value = row.get("tpep_pickup_datetime") or row.get("pickup_datetime")
    if value is None:
        return datetime.min
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay NYC taxi Parquet to Kafka")
    parser.add_argument("--file", required=True, type=Path, help="Parquet file path")
    parser.add_argument(
        "--bootstrap-servers",
        default=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
    )
    parser.add_argument(
        "--registry-url",
        default=os.getenv("SCHEMA_REGISTRY_URL", "http://localhost:8081"),
    )
    parser.add_argument("--schema-version", choices=["v1", "v2"], default=None)
    parser.add_argument(
        "--compression-factor",
        type=float,
        default=4320.0,
        help="Replay speed multiplier (4320 ≈ 30 days in 10 minutes)",
    )
    parser.add_argument("--max-records", type=int, default=None, help="Limit records for testing")
    args = parser.parse_args()

    if not args.file.exists():
        print(f"File not found: {args.file}", file=sys.stderr)
        return 1

    run(
        file_path=args.file,
        bootstrap_servers=args.bootstrap_servers,
        registry_url=args.registry_url,
        schema_version=args.schema_version,
        compression_factor=args.compression_factor,
        max_records=args.max_records,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
