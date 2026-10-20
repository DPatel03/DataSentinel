"""Evaluation metrics for classification, repair, latency, and cost."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from agents.coordinator import CoordinatorAgent
from agents.heuristics import classify_heuristic
from agents.models import DLQPayload, FailureClass


@dataclass
class ClassificationMetrics:
    total: int = 0
    correct: int = 0
    per_class_correct: dict[str, int] = field(default_factory=dict)
    per_class_total: dict[str, int] = field(default_factory=dict)
    hallucinations: int = 0
    hallucination_checked: int = 0
    latencies_ms: list[float] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return round(self.correct / self.total, 4) if self.total else 0.0

    @property
    def hallucination_rate(self) -> float:
        denom = self.hallucination_checked or self.total
        return round(self.hallucinations / denom, 4) if denom else 0.0

    def per_class_accuracy(self) -> dict[str, float]:
        return {
            cls: round(self.per_class_correct.get(cls, 0) / total, 4)
            for cls, total in self.per_class_total.items()
            if total > 0
        }

    def latency_percentiles(self) -> dict[str, float]:
        if not self.latencies_ms:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0}
        sorted_lat = sorted(self.latencies_ms)
        n = len(sorted_lat)

        def pct(p: float) -> float:
            idx = min(int(n * p), n - 1)
            return round(sorted_lat[idx], 2)

        return {"p50": pct(0.5), "p95": pct(0.95), "p99": pct(0.99)}


@dataclass
class RepairMetrics:
    total: int = 0
    correct: int = 0
    validation_passed: int = 0

    @property
    def accuracy(self) -> float:
        return round(self.correct / self.total, 4) if self.total else 0.0

    @property
    def validation_pass_rate(self) -> float:
        return round(self.validation_passed / self.total, 4) if self.total else 0.0


def _classify_sample(payload: DLQPayload, use_coordinator: bool) -> tuple[str, float]:
    start = time.perf_counter()
    if use_coordinator:
        coordinator = CoordinatorAgent()
        result = coordinator.process(payload).classification
    else:
        result = classify_heuristic(payload)
    elapsed_ms = (time.perf_counter() - start) * 1000
    return result.failure_class.value, elapsed_ms


def evaluate_classification(
    samples: list[dict],
    *,
    use_coordinator: bool = False,
    skip_clean: bool = True,
) -> ClassificationMetrics:
    metrics = ClassificationMetrics()
    for sample in samples:
        expected = sample["expected_class"]
        if expected == "clean":
            payload = DLQPayload.model_validate(sample["payload"])
            predicted, latency = _classify_sample(payload, use_coordinator)
            metrics.latencies_ms.append(latency)
            metrics.hallucination_checked += 1
            # Inventing a specific failure on a clean record is a hallucination.
            # upstream_bug is the honest "unknown / do not auto-act" bucket.
            if predicted != FailureClass.UPSTREAM_BUG.value:
                metrics.hallucinations += 1
            if skip_clean:
                continue
            metrics.total += 1
            continue

        payload = DLQPayload.model_validate(sample["payload"])
        predicted, latency = _classify_sample(payload, use_coordinator)
        metrics.total += 1
        metrics.latencies_ms.append(latency)
        metrics.per_class_total[expected] = metrics.per_class_total.get(expected, 0) + 1
        if predicted == expected:
            metrics.correct += 1
            metrics.per_class_correct[expected] = metrics.per_class_correct.get(expected, 0) + 1

    return metrics


def evaluate_repair(samples: list[dict]) -> RepairMetrics:
    metrics = RepairMetrics()
    coordinator = CoordinatorAgent()

    for sample in samples:
        if sample.get("expected_class") != "data_entry_error":
            continue
        payload = DLQPayload.model_validate(sample["payload"])
        outcome = coordinator.process(payload)
        metrics.total += 1
        if not outcome.repair:
            continue
        if outcome.repair.validation_passed:
            metrics.validation_passed += 1
        expected_val = sample.get("expected_repaired_value")
        field_name = sample.get("expected_repair_field") or outcome.repair.field_repaired
        if expected_val is not None and field_name:
            actual = outcome.repair.repaired_record.get(field_name)
            if actual is not None and abs(float(actual) - float(expected_val)) < 0.01:
                metrics.correct += 1
        elif outcome.repair.validation_passed:
            metrics.correct += 1

    return metrics


def evaluate_consistency(
    samples: list[dict],
    classify_fn: Callable[[DLQPayload], str],
    runs: int = 5,
) -> float:
    """Measure classification consistency across repeated runs on ambiguous records."""
    ambiguous = [s for s in samples if s.get("adversarial_type") == "ambiguous_class"]
    if not ambiguous:
        return 1.0

    consistent = 0
    for sample in ambiguous:
        payload = DLQPayload.model_validate(sample["payload"])
        predictions = [classify_fn(payload) for _ in range(runs)]
        if len(set(predictions)) == 1:
            consistent += 1
    return round(consistent / len(ambiguous), 4)


def evaluate_degradation(
    samples: list[dict],
    batches: int = 10,
) -> dict[str, Any]:
    """Gradually degrade data quality over batches; measure accuracy drop."""
    dirty = [s for s in samples if s.get("category") == "dirty_real"]
    if not dirty:
        return {"drop_at_batch": None, "accuracies": []}

    batch_size = max(1, len(dirty) // batches)
    accuracies: list[float] = []
    drop_at: int | None = None
    baseline: float | None = None

    for batch_idx in range(1, batches + 1):
        subset = dirty[: batch_idx * batch_size]
        # Simulate degradation by shuffling in more ambiguous cases
        noise = samples[batch_idx * 5 : batch_idx * 5 + batch_idx]
        combined = subset + noise
        m = evaluate_classification(combined, use_coordinator=False)
        accuracies.append(m.accuracy)
        if baseline is None:
            baseline = m.accuracy
        elif drop_at is None and baseline - m.accuracy >= 0.15:
            drop_at = batch_idx

    return {"drop_at_batch": drop_at, "accuracies": accuracies, "baseline": baseline}


def estimate_cost_per_1k(records: int, model: str = "gpt-4o-mini") -> dict[str, float]:
    """Rough token cost estimate (USD per 1K records)."""
    # gpt-4o-mini: ~$0.15/1M input, $0.60/1M output — ~800 tokens/record round trip
    tokens_per_record = 800
    if model == "gpt-4o-mini":
        cost_per_1k = records / 1000 * tokens_per_record / 1_000_000 * (0.15 + 0.60)
    else:
        # Llama 3 local — infra cost negligible for demo
        cost_per_1k = 0.0
    return {
        "model": model,
        "cost_per_1k_records_usd": round(cost_per_1k * (1000 / max(records, 1)), 4),
        "estimated_tokens_per_record": tokens_per_record,
    }
