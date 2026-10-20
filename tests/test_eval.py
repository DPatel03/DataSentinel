"""Tests for eval harness."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.adversarial import run_adversarial_suite
from eval.dataset.generate_dataset import generate_dataset
from eval.metrics import evaluate_classification, evaluate_repair
from eval.runner import run_eval

DATASET = Path(__file__).resolve().parents[1] / "eval" / "dataset" / "full_dataset.json"


@pytest.fixture(scope="module")
def dataset() -> list[dict]:
    if not DATASET.exists():
        DATASET.write_text(json.dumps(generate_dataset(), indent=2))
    return json.loads(DATASET.read_text())


def test_dataset_has_300_records(dataset: list[dict]) -> None:
    assert len(dataset) == 300


def test_dataset_categories(dataset: list[dict]) -> None:
    categories = {s.get("category") for s in dataset}
    assert "dirty_real" in categories
    assert "synthetic_edge" in categories
    assert "adversarial_clean" in categories or any(
        s.get("adversarial_type") for s in dataset
    )


def test_classification_accuracy_above_threshold(dataset: list[dict]) -> None:
    metrics = evaluate_classification(dataset, use_coordinator=False)
    assert metrics.total > 0
    assert metrics.accuracy >= 0.9
    per_class = metrics.per_class_accuracy()
    for cls in (
        "data_entry_error",
        "genuine_anomaly",
        "schema_drift",
        "upstream_bug",
        "known_edge_case",
    ):
        assert per_class.get(cls, 0) >= 0.9, f"{cls} accuracy {per_class.get(cls)}"


def test_repair_metrics(dataset: list[dict]) -> None:
    metrics = evaluate_repair(dataset)
    assert metrics.total > 0
    assert metrics.validation_pass_rate >= 0.5


def test_adversarial_suite(dataset: list[dict]) -> None:
    results = run_adversarial_suite(dataset)
    assert results.hallucination_injection.total >= 0
    assert 0.0 <= results.ambiguous_consistency <= 1.0


def test_eval_runner_produces_mlflow_results(dataset: list[dict], tmp_path: Path) -> None:
    ds_path = tmp_path / "test_dataset.json"
    ds_path.write_text(json.dumps(dataset))
    results = run_eval(
        dataset_path=ds_path,
        experiment_name="datasentinel-test",
        run_adversarial=True,
    )
    assert "classification_accuracy" in results
    assert "latency_ms" in results
    assert results["dataset_size"] == 300
