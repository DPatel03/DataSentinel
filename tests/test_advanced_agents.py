"""Tests for advanced agents (schema evolution, anomaly, escalation, prompts)."""

from __future__ import annotations

from agents.agent_outputs import SchemaEvolutionResult
from agents.anomaly_enrichment import AnomalyEnrichmentAgent
from agents.coordinator import CoordinatorAgent
from agents.models import DLQPayload, FailureClass
from agents.prompt_registry.registry import PromptRegistry
from agents.schema_evolution import SchemaEvolutionAgent


def _dlq(rule: str, record: dict | None) -> DLQPayload:
    return DLQPayload(
        record=record,
        rule_violated=rule,
        contract_version="1.0.0",
        timestamp="2026-06-16T12:00:00+00:00",
        sample_good_records=[],
    )


def test_schema_evolution_agent_mock():
    payload = _dlq("avro_deserialization_failed", None)
    from agents.heuristics import classify_heuristic

    classification = classify_heuristic(payload)
    agent = SchemaEvolutionAgent()
    result = agent.handle(payload, classification)
    assert isinstance(result, SchemaEvolutionResult)
    assert result.detected_schema_version in ("v1", "v2", "unknown")
    assert result.confidence >= 0.85


def test_anomaly_known_pattern_reclassify():
    payload = _dlq(
        "trip_distance_range",
        {
            "pickup_datetime": "2019-01-01T10:00:00",
            "dropoff_datetime": "2019-01-01T10:30:00",
            "fare_amount": 50.0,
            "trip_distance": 150.0,
            "total_amount": 60.0,
            "schema_version": "v1",
        },
    )
    from agents.heuristics import classify_heuristic

    classification = classify_heuristic(payload)
    assert classification.failure_class == FailureClass.GENUINE_ANOMALY

    agent = AnomalyEnrichmentAgent()
    reclassified = agent.check_known_pattern(payload, classification)
    assert reclassified is not None
    assert reclassified.failure_class == FailureClass.KNOWN_EDGE_CASE


def test_coordinator_schema_drift_path():
    payload = _dlq("avro_deserialization_failed", None)
    coordinator = CoordinatorAgent(db_dsn="postgresql://invalid/will/not/connect")
    outcome = coordinator.process(payload, record_key="test-key")
    assert outcome.classification.failure_class == FailureClass.SCHEMA_DRIFT
    assert outcome.schema_evolution is not None


def test_coordinator_anomaly_routes_enrichment():
    payload = _dlq(
        "max_trip_speed_mph",
        {
            "pickup_datetime": "2019-01-01T10:00:00",
            "dropoff_datetime": "2019-01-01T10:05:00",
            "fare_amount": 20.0,
            "trip_distance": 50.0,
            "total_amount": 25.0,
            "schema_version": "v1",
        },
    )
    coordinator = CoordinatorAgent()
    outcome = coordinator.process(payload, record_key="speed-test")
    assert outcome.classification.failure_class == FailureClass.GENUINE_ANOMALY
    assert outcome.anomaly is not None
    assert outcome.anomaly.routed_to_anomaly
    assert 1 <= outcome.anomaly.severity <= 5


def test_prompt_registry_eval():
    registry = PromptRegistry()
    accuracy, method = registry.evaluate_classifier()
    assert 0.0 <= accuracy <= 1.0
    assert method == "heuristic_labeled_set"
    assert registry.evaluate_classifier_prompt() == accuracy
