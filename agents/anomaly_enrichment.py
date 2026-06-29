"""Anomaly Enrichment agent — handles genuine_anomaly and known_edge_case."""

from __future__ import annotations

import json
import logging
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

from pydantic import BaseModel, Field

from agents.llm_client import LLMClient
from agents.models import ClassificationResult, DLQPayload, FailureClass
from agents.week3_models import AnomalyEnrichmentResult
from validation.config import timescaledb_dsn

logger = logging.getLogger(__name__)


class _AnomalyLLMOutput(BaseModel):
    explanation: str
    severity: int = Field(ge=1, le=5)
    suggested_action: str


# Built-in known patterns (also seeded in DB)
KNOWN_PATTERNS: list[dict[str, Any]] = [
    {
        "pattern_name": "zero_distance_trip",
        "rule_violated": "trip_distance_range",
        "field": "trip_distance",
        "match": lambda r: r.get("trip_distance") == 0,
        "explanation": "Zero-distance trip — known edge case (passenger cancel or meter reset).",
        "severity": 2,
        "action": "Monitor; do not auto-repair.",
    },
    {
        "pattern_name": "extreme_distance",
        "rule_violated": "trip_distance_range",
        "field": "trip_distance",
        "match": lambda r: r.get("trip_distance") is not None and float(r["trip_distance"]) > 100,
        "explanation": "Extreme trip distance — known long-haul or GPS error pattern.",
        "severity": 4,
        "action": "Flag for manual review; exclude from fare aggregates.",
    },
]


class AnomalyHistoryStore:
    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn or timescaledb_dsn()

    def find_known_pattern(self, payload: DLQPayload) -> dict[str, Any] | None:
        record = payload.record or {}
        rule = payload.rule_violated

        for pattern in KNOWN_PATTERNS:
            if pattern["rule_violated"] == rule and pattern["match"](record):
                return pattern

        try:
            with psycopg2.connect(self.dsn) as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT pattern_name, rule_violated, field_name, explanation,
                               severity, suggested_action
                        FROM anomaly_patterns
                        WHERE rule_violated = %s AND active = TRUE
                        """,
                        (rule,),
                    )
                    rows = cur.fetchall()
            for row in rows:
                field = row["field_name"]
                if field and record.get(field) is not None:
                    return dict(row)
        except psycopg2.Error as exc:
            logger.debug("Anomaly pattern DB lookup skipped: %s", exc)

        return None

    def record_anomaly(self, result: AnomalyEnrichmentResult, payload: DLQPayload, record_key: str) -> None:
        try:
            with psycopg2.connect(self.dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO anomaly_history (
                            time, record_key, rule_violated, pattern_name,
                            severity, explanation, record_payload
                        ) VALUES (now(), %s, %s, %s, %s, %s, %s::jsonb)
                        """,
                        (
                            record_key,
                            payload.rule_violated,
                            result.pattern_name,
                            result.severity,
                            result.explanation,
                            json.dumps(payload.record, default=str),
                        ),
                    )
                conn.commit()
        except Exception as exc:
            logger.warning("Failed to record anomaly history: %s", exc)


class AnomalyEnrichmentAgent:
    def __init__(self, llm: LLMClient | None = None, history: AnomalyHistoryStore | None = None) -> None:
        self.llm = llm or LLMClient()
        self.history = history or AnomalyHistoryStore()

    def check_known_pattern(
        self, payload: DLQPayload, classification: ClassificationResult
    ) -> ClassificationResult | None:
        """Reclassify genuine_anomaly to known_edge_case if pattern matches."""
        if classification.failure_class != FailureClass.GENUINE_ANOMALY:
            return None

        pattern = self.history.find_known_pattern(payload)
        if not pattern:
            return None

        return classification.model_copy(
            update={
                "failure_class": FailureClass.KNOWN_EDGE_CASE,
                "confidence": max(classification.confidence, 0.85),
                "explanation": pattern.get("explanation", classification.explanation),
                "requires_human_review": False,
            }
        )

    def enrich(
        self,
        payload: DLQPayload,
        classification: ClassificationResult,
        route: bool = True,
    ) -> AnomalyEnrichmentResult:
        record = dict(payload.record or {})
        pattern = self.history.find_known_pattern(payload)

        if pattern:
            result = AnomalyEnrichmentResult(
                record=record,
                explanation=pattern.get("explanation", classification.explanation),
                severity=int(pattern.get("severity", 3)),
                suggested_action=pattern.get("suggested_action", pattern.get("action", "Monitor")),
                matched_known_pattern=True,
                pattern_name=pattern.get("pattern_name"),
                reclassified_from=FailureClass.GENUINE_ANOMALY
                if classification.failure_class == FailureClass.KNOWN_EDGE_CASE
                else None,
                routed_to_anomaly=route,
            )
            return result

        if self.llm.mock:
            return self._mock_enrich(record, payload, classification, route)

        try:
            llm_input = {**payload.model_dump(), "classification": classification.model_dump()}
            raw = self.llm.complete_json("anomaly", llm_input, _AnomalyLLMOutput)
            return AnomalyEnrichmentResult(
                record=record,
                explanation=raw.explanation,
                severity=raw.severity,
                suggested_action=raw.suggested_action,
                routed_to_anomaly=route,
            )
        except Exception as exc:
            logger.warning("Anomaly LLM failed: %s", exc)
            return self._mock_enrich(record, payload, classification, route)

    def _mock_enrich(
        self,
        record: dict,
        payload: DLQPayload,
        classification: ClassificationResult,
        route: bool,
    ) -> AnomalyEnrichmentResult:
        rule = payload.rule_violated
        severity = 3
        action = "Flag record and exclude from downstream aggregates"

        if rule == "max_trip_speed_mph":
            severity = 4
            explanation = "Implied trip speed exceeds physical limits — possible GPS corruption or fraud."
        elif rule == "trip_distance_range":
            severity = 4
            explanation = "Trip distance outside normal NYC taxi range."
        else:
            explanation = classification.explanation or f"Anomaly on rule {rule}"

        return AnomalyEnrichmentResult(
            record=record,
            explanation=explanation,
            severity=severity,
            suggested_action=action,
            routed_to_anomaly=route,
        )
