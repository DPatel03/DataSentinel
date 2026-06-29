"""Shared record validation, routing, and breach writing logic."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from confluent_kafka import Producer
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.avro import AvroDeserializer
from confluent_kafka.serialization import MessageField, SerializationContext

from validation.contract import load_contract, validate_record
from validation.spark_job.breach_writer import BreachWriter
from validation.spark_job.good_record_buffer import GoodRecordBuffer

RAW_TOPIC = "taxi.rides.raw"


class RecordProcessor:
    def __init__(
        self,
        bootstrap_servers: str,
        registry_url: str,
        db_dsn: str,
        contract_version: str = "1.0.0",
    ) -> None:
        self.contract_version = contract_version
        self.contract = load_contract()
        self.good_buffer = GoodRecordBuffer(max_size=1000)
        self.breach_writer = BreachWriter(db_dsn)
        self._pending_breaches: list[dict[str, Any]] = []

        registry = SchemaRegistryClient({"url": registry_url})
        self.deserializer = AvroDeserializer(registry)

        producer_config = {"bootstrap.servers": bootstrap_servers}
        self.validated_producer = Producer(producer_config)
        self.dlq_producer = Producer(producer_config)

    def _deserialize(self, payload: bytes | None) -> dict[str, Any] | None:
        if payload is None:
            return None
        try:
            return self.deserializer(
                payload, SerializationContext(RAW_TOPIC, MessageField.VALUE)
            )
        except Exception:
            return None

    def _publish_json(self, producer: Producer, topic: str, key: str, payload: dict[str, Any]) -> None:
        producer.produce(
            topic=topic,
            key=key.encode("utf-8"),
            value=json.dumps(payload, default=str).encode("utf-8"),
        )

    def process_message(self, payload: bytes | None) -> bool:
        """Process one Kafka message. Returns True if handled."""
        record = self._deserialize(payload)
        if record is None:
            dlq_payload = {
                "record": None,
                "rule_violated": "avro_deserialization_failed",
                "contract_version": self.contract_version,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "sample_good_records": self.good_buffer.nearest({"pickup_datetime": ""}),
            }
            self._publish_json(self.dlq_producer, "taxi.rides.dead-letter", "invalid", dlq_payload)
            return True

        is_valid, rule_violated, field_name = validate_record(record, self.contract)
        key = record.get("pickup_datetime", "unknown")

        if is_valid:
            self.good_buffer.add(record)
            self._publish_json(self.validated_producer, "taxi.rides.validated", key, record)
        else:
            dlq_payload = {
                "record": record,
                "rule_violated": rule_violated,
                "contract_version": self.contract_version,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "sample_good_records": self.good_buffer.nearest(record, count=5),
            }
            self._publish_json(self.dlq_producer, "taxi.rides.dead-letter", key, dlq_payload)
            self._pending_breaches.append(
                {
                    "time": datetime.now(timezone.utc),
                    "rule_name": rule_violated,
                    "field_name": field_name,
                    "contract_version": self.contract_version,
                    "failure_count": 1,
                    "sample_record": record,
                }
            )
        return True

    def flush(self) -> int:
        """Flush producers and write pending breaches. Returns breach count."""
        self.validated_producer.flush()
        self.dlq_producer.flush()
        breach_count = len(self._pending_breaches)
        if self._pending_breaches:
            self.breach_writer.write_breaches(self._pending_breaches)
            self._pending_breaches.clear()
        return breach_count

    def close(self) -> None:
        self.flush()
        self.breach_writer.close()
