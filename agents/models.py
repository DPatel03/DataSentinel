"""Pydantic models for agent inputs and outputs."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class FailureClass(str, Enum):
    SCHEMA_DRIFT = "schema_drift"
    DATA_ENTRY_ERROR = "data_entry_error"
    GENUINE_ANOMALY = "genuine_anomaly"
    UPSTREAM_BUG = "upstream_bug"
    KNOWN_EDGE_CASE = "known_edge_case"


class DLQPayload(BaseModel):
    record: dict[str, Any] | None
    rule_violated: str
    contract_version: str
    timestamp: str
    sample_good_records: list[dict[str, Any]] = Field(default_factory=list)


class ClassificationResult(BaseModel):
    failure_class: FailureClass
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str
    affected_field: str | None = None
    suggested_fix: str | None = None
    requires_human_review: bool = False
    source: str = "heuristic"  # heuristic | llm

    @field_validator("confidence")
    @classmethod
    def round_confidence(cls, value: float) -> float:
        return round(value, 4)


class RepairResult(BaseModel):
    repaired_record: dict[str, Any]
    field_repaired: str | None
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str
    validation_passed: bool
    routed_to_repaired: bool = False


class TriageOutcome(BaseModel):
    dlq: DLQPayload
    classification: ClassificationResult
    repair: RepairResult | None = None
    schema_evolution: "SchemaEvolutionResult | None" = None
    anomaly: "AnomalyEnrichmentResult | None" = None
    escalation: "EscalationResult | None" = None


# Resolve forward refs for week3 models
from agents.week3_models import AnomalyEnrichmentResult, EscalationResult, SchemaEvolutionResult  # noqa: E402

TriageOutcome.model_rebuild()
