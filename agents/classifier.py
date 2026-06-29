"""Classifier agent — LLM with heuristic fallback."""

from __future__ import annotations

import logging

from agents.config import HEURISTIC_CONFIDENCE_THRESHOLD
from agents.heuristics import classify_heuristic
from agents.llm_client import LLMClient
from agents.models import ClassificationResult, DLQPayload, FailureClass

logger = logging.getLogger(__name__)


class ClassifierAgent:
    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()

    def classify(self, payload: DLQPayload) -> ClassificationResult:
        heuristic = classify_heuristic(payload)

        if heuristic.confidence >= HEURISTIC_CONFIDENCE_THRESHOLD:
            logger.info(
                "Heuristic classification: %s (%.2f)",
                heuristic.failure_class.value,
                heuristic.confidence,
            )
            return heuristic

        if self.llm.mock:
            logger.info("Mock LLM mode — using heuristic result")
            return heuristic

        try:
            llm_result = self.llm.complete_json(
                "classifier",
                payload.model_dump(),
                ClassificationResult,
            )
            llm_result.source = "llm"
            logger.info(
                "LLM classification: %s (%.2f)",
                llm_result.failure_class.value,
                llm_result.confidence,
            )
            return llm_result
        except Exception as exc:
            logger.warning("LLM classifier failed, falling back to heuristic: %s", exc)
            heuristic.requires_human_review = True
            return heuristic
