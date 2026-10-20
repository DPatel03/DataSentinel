#!/usr/bin/env python3
"""Pure-Python Kafka streaming validator (no Java/Spark required)."""

from __future__ import annotations

import argparse
import os
import signal
import sys
import uuid

from confluent_kafka import Consumer, KafkaError

from validation.config import load_env, timescaledb_dsn
from validation.record_processor import RecordProcessor

RUNNING = True


def _handle_stop(signum, frame) -> None:  # noqa: ARG001
    global RUNNING
    RUNNING = False
    print("\nShutting down validator...")


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser(description="Python Kafka streaming validator")
    parser.add_argument("--bootstrap-servers", default=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"))
    parser.add_argument("--registry-url", default=os.getenv("SCHEMA_REGISTRY_URL", "http://localhost:8081"))
    parser.add_argument("--db-dsn", default=timescaledb_dsn())
    parser.add_argument("--group-id", default="datasentinel-validator")
    parser.add_argument(
        "--from-beginning",
        action="store_true",
        help="Use a fresh consumer group so all messages are read (useful in dev)",
    )
    parser.add_argument("--flush-every", type=int, default=50, help="Flush producers/DB every N messages")
    args = parser.parse_args()

    group_id = args.group_id
    if args.from_beginning:
        group_id = f"{args.group_id}-{uuid.uuid4().hex[:8]}"
        print(f"Reading from beginning with fresh group: {group_id}")

    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    processor = RecordProcessor(
        bootstrap_servers=args.bootstrap_servers,
        registry_url=args.registry_url,
        db_dsn=args.db_dsn,
    )

    consumer = Consumer(
        {
            "bootstrap.servers": args.bootstrap_servers,
            "group.id": group_id,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )
    consumer.subscribe(["taxi.rides.raw"])

    print("Validator running (Python). Waiting for messages on taxi.rides.raw ...")
    processed = 0

    try:
        while RUNNING:
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                print(f"Consumer error: {msg.error()}", file=sys.stderr)
                continue

            processor.process_message(msg.value())
            consumer.commit(asynchronous=True)
            processed += 1

            if processed % args.flush_every == 0:
                breaches = processor.flush()
                print(f"Processed {processed} messages ({breaches} breaches in last batch)")
    finally:
        breaches = processor.flush()
        processor.close()
        consumer.close()
        print(f"Stopped. Total processed: {processed}, final breaches flushed: {breaches}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
