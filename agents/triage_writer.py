"""Persist triage, repair, and agent events to TimescaleDB."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import psycopg2

from agents.models import TriageOutcome


class TriageWriter:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self._conn = None

    def connect(self) -> None:
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self.dsn)

    def close(self) -> None:
        if self._conn and not self._conn.closed:
            self._conn.close()

    def write_outcome(self, outcome: TriageOutcome, record_key: str) -> None:
        self.connect()
        now = datetime.now(timezone.utc)
        classification = outcome.classification
        repair = outcome.repair

        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO triage_events (
                    time, record_key, rule_violated, failure_class, confidence,
                    explanation, affected_field, requires_human_review,
                    classifier_source, raw_payload
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    now,
                    record_key,
                    outcome.dlq.rule_violated,
                    classification.failure_class.value,
                    classification.confidence,
                    classification.explanation,
                    classification.affected_field,
                    classification.requires_human_review,
                    classification.source,
                    json.dumps(outcome.dlq.model_dump(), default=str),
                ),
            )

            if repair:
                cur.execute(
                    """
                    INSERT INTO repair_attempts (
                        time, record_key, original_record, repaired_record,
                        field_repaired, confidence, validation_passed, routed_to_repaired
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        now,
                        record_key,
                        json.dumps(outcome.dlq.record, default=str),
                        json.dumps(repair.repaired_record, default=str),
                        repair.field_repaired,
                        repair.confidence,
                        repair.validation_passed,
                        repair.routed_to_repaired,
                    ),
                )

            if outcome.schema_evolution:
                se = outcome.schema_evolution
                cur.execute(
                    """
                    INSERT INTO schema_evolution_events (
                        time, record_key, detected_schema_version, drift_description,
                        affected_fields, confidence, registry_updated,
                        github_issue_url, ge_suite_code
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        now,
                        record_key,
                        se.detected_schema_version,
                        se.drift_description,
                        se.affected_fields,
                        se.confidence,
                        se.registry_updated,
                        se.github_issue_url,
                        se.ge_suite_code,
                    ),
                )

        self._conn.commit()
