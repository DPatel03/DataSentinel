#!/usr/bin/env python3
"""Kafka consumer — full AI triage pipeline."""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import uuid

from confluent_kafka import Consumer, KafkaError, Producer

from agents.config import ANOMALY_TOPIC, DLQ_TOPIC, REPAIRED_TOPIC
from agents.coordinator import CoordinatorAgent
from agents.llm_client import LLMClient
from agents.models import DLQPayload
from agents.prompt_registry.registry import PromptRegistry
from agents.triage_writer import TriageWriter
from ingestion.keys import ride_key
from validation.config import load_env, timescaledb_dsn

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

RUNNING = True


def _handle_stop(signum, frame) -> None:  # noqa: ARG001
    global RUNNING
    RUNNING = False
    logger.info("Shutting down triage service...")


def _publish_json(producer: Producer, topic: str, key: str, payload: dict) -> None:
    producer.produce(
        topic=topic,
        key=key.encode("utf-8"),
        value=json.dumps(payload, default=str).encode("utf-8"),
    )


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser(description="DataSentinel triage service")
    parser.add_argument("--bootstrap-servers", default=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"))
    parser.add_argument("--db-dsn", default=timescaledb_dsn())
    parser.add_argument("--group-id", default="datasentinel-triage")
    parser.add_argument("--from-beginning", action="store_true")
    parser.add_argument("--mock-llm", action="store_true", help="Force heuristic/mock mode (no OpenAI calls)")
    parser.add_argument("--seed-prompts", action="store_true", help="Seed prompt registry from files")
    args = parser.parse_args()

    group_id = args.group_id
    if args.from_beginning:
        group_id = f"{args.group_id}-{uuid.uuid4().hex[:8]}"
        logger.info("Fresh consumer group: %s", group_id)

    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    registry = PromptRegistry(args.db_dsn)
    if args.seed_prompts:
        registry.seed_from_files()
        logger.info("Prompt registry seeded")

    llm = LLMClient(mock=args.mock_llm)
    if llm.mock:
        logger.info("Running in mock/heuristic mode (set OPENAI_API_KEY for real LLM calls)")

    coordinator = CoordinatorAgent(db_dsn=args.db_dsn, llm=llm)
    writer = TriageWriter(args.db_dsn)
    producer = Producer({"bootstrap.servers": args.bootstrap_servers})

    consumer = Consumer(
        {
            "bootstrap.servers": args.bootstrap_servers,
            "group.id": group_id,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )
    consumer.subscribe([DLQ_TOPIC])

    stats = {"processed": 0, "repaired": 0, "anomaly": 0, "escalated": 0, "schema": 0}

    logger.info("Triage service listening on %s", DLQ_TOPIC)

    try:
        while RUNNING:
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                logger.error("Consumer error: %s", msg.error())
                continue

            try:
                raw = json.loads(msg.value().decode("utf-8"))
                payload = DLQPayload.model_validate(raw)
            except Exception as exc:
                logger.error("Invalid DLQ payload: %s", exc)
                consumer.commit(asynchronous=True)
                continue

            record_key = (
                msg.key().decode("utf-8")
                if msg.key()
                else ride_key(payload.record)
            )

            try:
                outcome = coordinator.process(payload, record_key=record_key)
            except Exception as exc:
                logger.exception("Triage failed for %s: %s", record_key, exc)
                consumer.commit(asynchronous=True)
                continue

            writer.write_outcome(outcome, record_key)

            if outcome.repair and outcome.repair.routed_to_repaired:
                _publish_json(
                    producer,
                    REPAIRED_TOPIC,
                    record_key,
                    {
                        "original_record": payload.record,
                        "repaired_record": outcome.repair.repaired_record,
                        "field_repaired": outcome.repair.field_repaired,
                        "confidence": outcome.repair.confidence,
                        "classification": outcome.classification.model_dump(),
                        "rule_violated": payload.rule_violated,
                        "repaired_at": payload.timestamp,
                    },
                )
                stats["repaired"] += 1

            if outcome.anomaly and outcome.anomaly.routed_to_anomaly:
                _publish_json(
                    producer,
                    ANOMALY_TOPIC,
                    record_key,
                    {
                        "record": outcome.anomaly.record,
                        "explanation": outcome.anomaly.explanation,
                        "severity": outcome.anomaly.severity,
                        "suggested_action": outcome.anomaly.suggested_action,
                        "pattern_name": outcome.anomaly.pattern_name,
                        "classification": outcome.classification.model_dump(),
                        "rule_violated": payload.rule_violated,
                    },
                )
                stats["anomaly"] += 1

            if outcome.escalation:
                stats["escalated"] += 1

            if outcome.schema_evolution:
                stats["schema"] += 1

            logger.info(
                "Triage: class=%s repair=%s anomaly=%s escalate=%s schema=%s",
                outcome.classification.failure_class.value,
                bool(outcome.repair and outcome.repair.routed_to_repaired),
                bool(outcome.anomaly and outcome.anomaly.routed_to_anomaly),
                bool(outcome.escalation),
                bool(outcome.schema_evolution),
            )

            stats["processed"] += 1
            producer.poll(0)
            consumer.commit(asynchronous=True)

    finally:
        producer.flush()
        writer.close()
        consumer.close()
        logger.info("Stopped. Stats: %s", stats)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
