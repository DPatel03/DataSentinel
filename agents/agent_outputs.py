"""Extended agent output models (schema evolution, anomaly, escalation)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SchemaEvolutionResult(BaseModel):
    detected_schema_version: str
    drift_description: str
    affected_fields: list[str] = Field(default_factory=list)
    ge_suite_code: str
    contract_suggestion: str
    confidence: float = Field(ge=0.0, le=1.0)
    registry_updated: bool = False
    github_issue_url: str | None = None
    github_issue_number: int | None = None


class AnomalyEnrichmentResult(BaseModel):
    record: dict[str, Any]
    explanation: str
    severity: int = Field(ge=1, le=5)
    suggested_action: str
    matched_known_pattern: bool = False
    pattern_name: str | None = None
    reclassified_from: str | None = None
    routed_to_anomaly: bool = False


class EscalationResult(BaseModel):
    summary: str
    recommended_action: str
    review_queue_id: int | None = None
    slack_sent: bool = False
    status: str = "open"
