"""Adversarial evaluation suite."""

from __future__ import annotations

from dataclasses import dataclass

from agents.heuristics import classify_heuristic
from agents.models import DLQPayload
from eval.metrics import (
    ClassificationMetrics,
    evaluate_classification,
    evaluate_consistency,
    evaluate_degradation,
)


@dataclass
class AdversarialResults:
    hallucination_injection: ClassificationMetrics
    ambiguous_consistency: float
    degradation: dict
    passed: bool

    def to_dict(self) -> dict:
        return {
            "hallucination_rate": self.hallucination_injection.hallucination_rate,
            "hallucination_samples": self.hallucination_injection.total,
            "ambiguous_consistency": self.ambiguous_consistency,
            "degradation": self.degradation,
            "passed": self.passed,
        }


def run_adversarial_suite(samples: list[dict]) -> AdversarialResults:
    clean_samples = [s for s in samples if s.get("adversarial_type") == "hallucination_injection"]
    hallucination = evaluate_classification(clean_samples, use_coordinator=False)

    def _classify(payload: DLQPayload) -> str:
        return classify_heuristic(payload).failure_class.value

    consistency = evaluate_consistency(samples, _classify, runs=5)
    degradation = evaluate_degradation(samples)

    # Pass if hallucination rate < 20% on clean records and consistency > 50%
    passed = (
        hallucination.hallucination_rate <= 0.2
        and consistency >= 0.5
    )

    return AdversarialResults(
        hallucination_injection=hallucination,
        ambiguous_consistency=consistency,
        degradation=degradation,
        passed=passed,
    )
