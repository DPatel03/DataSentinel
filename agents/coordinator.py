"""Coordinator agent — routes DLQ failures to specialized sub-agents."""

from __future__ import annotations

import logging

from agents.anomaly_enrichment import AnomalyEnrichmentAgent
from agents.classifier import ClassifierAgent
from agents.escalation import EscalationAgent
from agents.llm_client import LLMClient
from agents.models import DLQPayload, FailureClass, TriageOutcome
from agents.repair import RepairAgent
from agents.schema_evolution import SchemaEvolutionAgent

logger = logging.getLogger(__name__)


class CoordinatorAgent:
    def __init__(
        self,
        classifier: ClassifierAgent | None = None,
        repair: RepairAgent | None = None,
        schema_evolution: SchemaEvolutionAgent | None = None,
        anomaly: AnomalyEnrichmentAgent | None = None,
        escalation: EscalationAgent | None = None,
        db_dsn: str | None = None,
        llm: LLMClient | None = None,
    ) -> None:
        llm = llm or LLMClient()
        self.classifier = classifier or ClassifierAgent(llm=llm)
        self.repair = repair or RepairAgent(llm=llm)
        self.schema_evolution = schema_evolution or SchemaEvolutionAgent(llm=llm)
        self.anomaly = anomaly or AnomalyEnrichmentAgent(llm=llm)
        self.escalation = escalation or EscalationAgent(llm=llm)
        self.db_dsn = db_dsn

    def process(self, payload: DLQPayload, record_key: str = "unknown") -> TriageOutcome:
        logger.info("Triage started for rule=%s", payload.rule_violated)

        classification = self.classifier.classify(payload)

        # Known anomaly patterns may reclassify genuine_anomaly -> known_edge_case
        reclassified = self.anomaly.check_known_pattern(payload, classification)
        if reclassified:
            logger.info(
                "Reclassified %s -> %s (known pattern)",
                classification.failure_class.value,
                reclassified.failure_class.value,
            )
            classification = reclassified

        repair_result = None
        schema_result = None
        anomaly_result = None
        escalation_result = None

        if classification.failure_class == FailureClass.DATA_ENTRY_ERROR:
            repair_result = self.repair.repair(payload, classification)
            if repair_result and self.repair.should_route(repair_result):
                repair_result.routed_to_repaired = True

        elif classification.failure_class == FailureClass.SCHEMA_DRIFT:
            schema_result = self.schema_evolution.handle(payload, classification)

        elif classification.failure_class in (
            FailureClass.GENUINE_ANOMALY,
            FailureClass.KNOWN_EDGE_CASE,
        ):
            route = classification.failure_class == FailureClass.GENUINE_ANOMALY
            anomaly_result = self.anomaly.enrich(payload, classification, route=route)
            if anomaly_result.routed_to_anomaly:
                self.anomaly.history.record_anomaly(anomaly_result, payload, record_key)

        if classification.requires_human_review and self.db_dsn:
            escalation_result = self.escalation.escalate(
                payload, classification, record_key, self.db_dsn
            )

        return TriageOutcome(
            dlq=payload,
            classification=classification,
            repair=repair_result,
            schema_evolution=schema_result,
            anomaly=anomaly_result,
            escalation=escalation_result,
        )
