"""Tests for Week 2 agents (no API key required)."""

from __future__ import annotations

import pytest

from agents.coordinator import CoordinatorAgent
from agents.heuristics import classify_heuristic, repair_heuristic
from agents.llm_client import LLMClient
from agents.models import DLQPayload, FailureClass
from agents.repair import RepairAgent
from validation.contract import validate_record


def _dlq(rule: str, record: dict) -> DLQPayload:
    return DLQPayload(
        record=record,
        rule_violated=rule,
        contract_version="1.0.0",
        timestamp="2026-06-16T12:00:00+00:00",
        sample_good_records=[],
    )


def test_negative_fare_classified_as_data_entry_error():
    payload = _dlq(
        "fare_amount_range",
        {
            "pickup_datetime": "2019-01-01T08:30:00",
            "dropoff_datetime": "2019-01-01T08:45:00",
            "fare_amount": -14.5,
            "trip_distance": 2.5,
            "total_amount": 15.0,
            "schema_version": "v1",
        },
    )
    result = classify_heuristic(payload)
    assert result.failure_class == FailureClass.DATA_ENTRY_ERROR
    assert result.confidence >= 0.9
    assert result.affected_field == "fare_amount"


def test_negative_fare_repair_passes_validation():
    payload = _dlq(
        "fare_amount_range",
        {
            "pickup_datetime": "2019-01-01T08:30:00",
            "dropoff_datetime": "2019-01-01T08:45:00",
            "fare_amount": -14.5,
            "trip_distance": 2.5,
            "total_amount": 15.0,
            "schema_version": "v1",
        },
    )
    classification = classify_heuristic(payload)
    repair = repair_heuristic(payload, classification)
    assert repair is not None
    assert repair.validation_passed
    assert repair.repaired_record["fare_amount"] == 14.5


def test_swapped_datetimes_repair():
    payload = _dlq(
        "dropoff_after_pickup",
        {
            "pickup_datetime": "2019-01-01T09:00:00",
            "dropoff_datetime": "2019-01-01T08:30:00",
            "fare_amount": 12.0,
            "trip_distance": 2.0,
            "total_amount": 14.0,
            "schema_version": "v1",
        },
    )
    classification = classify_heuristic(payload)
    repair = repair_heuristic(payload, classification)
    assert repair is not None
    assert repair.validation_passed
    is_valid, _, _ = validate_record(repair.repaired_record)
    assert is_valid


def test_coordinator_end_to_end_mock():
    coordinator = CoordinatorAgent()
    payload = _dlq(
        "fare_amount_range",
        {
            "pickup_datetime": "2019-01-01T08:30:00",
            "dropoff_datetime": "2019-01-01T08:45:00",
            "fare_amount": -14.5,
            "trip_distance": 2.5,
            "total_amount": 15.0,
            "schema_version": "v1",
        },
    )
    outcome = coordinator.process(payload)
    assert outcome.classification.failure_class == FailureClass.DATA_ENTRY_ERROR
    assert outcome.repair is not None
    assert outcome.repair.validation_passed
    assert RepairAgent().should_route(outcome.repair)


def test_llm_client_mock_mode():
    client = LLMClient(mock=True)
    payload = _dlq("fare_amount_range", {"fare_amount": -10, "trip_distance": 1, "total_amount": 10, "schema_version": "v1",
                                          "pickup_datetime": "2019-01-01T08:00:00", "dropoff_datetime": "2019-01-01T08:15:00"})
    from agents.models import ClassificationResult

    result = client.complete_json("classifier", payload.model_dump(), ClassificationResult)
    assert result.failure_class == FailureClass.DATA_ENTRY_ERROR
