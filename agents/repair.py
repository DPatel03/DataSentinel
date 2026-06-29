"""Repair agent — fix data_entry_error records and re-validate."""

from __future__ import annotations

import logging

from pydantic import BaseModel

from agents.config import REPAIR_CONFIDENCE_THRESHOLD
from agents.heuristics import repair_heuristic
from agents.llm_client import LLMClient
from agents.models import ClassificationResult, DLQPayload, FailureClass, RepairResult
from validation.contract import validate_record

logger = logging.getLogger(__name__)


class _LLMRepairOutput(BaseModel):
    repaired_record: dict
    field_repaired: str | None = None
    confidence: float
    explanation: str


class RepairAgent:
    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()

    def repair(self, payload: DLQPayload, classification: ClassificationResult) -> RepairResult | None:
        if classification.failure_class != FailureClass.DATA_ENTRY_ERROR:
            logger.info("Skipping repair — failure_class=%s", classification.failure_class.value)
            return None

        heuristic_result = repair_heuristic(payload, classification)

        if self.llm.mock:
            if heuristic_result:
                logger.info("Mock repair applied via heuristics")
                return heuristic_result
            return None

        if heuristic_result and heuristic_result.validation_passed:
            logger.info("Heuristic repair passed validation")
            return heuristic_result

        try:
            llm_input = {
                **payload.model_dump(),
                "classification": classification.model_dump(),
            }
            llm_raw = self.llm.complete_json("repair", llm_input, _LLMRepairOutput)
            is_valid, rule_violated, _ = validate_record(llm_raw.repaired_record)
            result = RepairResult(
                repaired_record=llm_raw.repaired_record,
                field_repaired=llm_raw.field_repaired,
                confidence=llm_raw.confidence,
                explanation=llm_raw.explanation,
                validation_passed=is_valid,
            )
            if not is_valid:
                logger.warning("LLM repair failed validation: %s", rule_violated)
            return result
        except Exception as exc:
            logger.warning("LLM repair failed: %s", exc)
            if heuristic_result:
                return heuristic_result
            return None

    def should_route(self, repair: RepairResult) -> bool:
        return repair.validation_passed and repair.confidence >= REPAIR_CONFIDENCE_THRESHOLD
