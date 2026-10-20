#!/usr/bin/env python3
"""Main eval runner — logs metrics to MLflow and stdout."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.adversarial import run_adversarial_suite
from eval.dataset.generate_dataset import DATASET_PATH, generate_dataset
from eval.metrics import (
    estimate_cost_per_1k,
    evaluate_classification,
    evaluate_repair,
)

MLRUNS_DIR = ROOT / "mlruns"
DEFAULT_DATASET = DATASET_PATH


def _write_eval_snapshot(results: dict) -> None:
    MLRUNS_DIR.mkdir(parents=True, exist_ok=True)
    (MLRUNS_DIR / "eval_results.json").write_text(json.dumps(results, indent=2))


def _log_to_mlflow(results: dict, experiment_name: str, use_coordinator: bool, dataset_path: Path) -> None:
    _write_eval_snapshot(results)
    try:
        import mlflow
    except ImportError:
        return
    mlflow.set_tracking_uri(f"file://{MLRUNS_DIR}")
    mlflow.set_experiment(experiment_name)

    with mlflow.start_run(run_name=f"eval-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"):
        if results.get("prompt_version"):
            mlflow.set_tag("prompt_version", results["prompt_version"])
        mlflow.log_param("dataset_path", str(dataset_path))
        mlflow.log_param("dataset_size", results["dataset_size"])
        mlflow.log_param("use_coordinator", use_coordinator)
        for key in (
            "classification_accuracy",
            "repair_accuracy",
            "repair_validation_pass_rate",
            "hallucination_rate",
            "cost_gpt4o_mini_per_1k",
            "cost_llama3_per_1k",
        ):
            if key in results:
                mlflow.log_metric(key, results[key])
        for cls, acc in results.get("per_class_accuracy", {}).items():
            mlflow.log_metric(f"accuracy_{cls}", acc)
        for k, v in results.get("latency_ms", {}).items():
            mlflow.log_metric(f"latency_{k}_ms", v)
        if "adversarial" in results:
            mlflow.log_metric("adversarial_hallucination_rate", results["adversarial"]["hallucination_rate"])
            mlflow.log_metric("ambiguous_consistency", results["adversarial"]["ambiguous_consistency"])
            mlflow.log_metric("adversarial_passed", int(results["adversarial"]["passed"]))
        mlflow.log_dict(results, "eval_results.json")


def load_dataset(path: Path) -> list[dict]:
    if not path.exists():
        print(f"Dataset not found at {path}, generating...")
        dataset = generate_dataset()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dataset, indent=2))
    return json.loads(path.read_text())


def run_eval(
    dataset_path: Path = DEFAULT_DATASET,
    experiment_name: str = "datasentinel-eval",
    prompt_version: str | None = None,
    use_coordinator: bool = False,
    run_adversarial: bool = True,
) -> dict:
    samples = load_dataset(dataset_path)
    labeled = [s for s in samples if s.get("expected_class") != "clean"]

    classification = evaluate_classification(samples, use_coordinator=use_coordinator)
    repair = evaluate_repair(samples)
    adversarial = run_adversarial_suite(samples) if run_adversarial else None
    cost_gpt = estimate_cost_per_1k(len(labeled), "gpt-4o-mini")
    cost_llama = estimate_cost_per_1k(len(labeled), "llama-3-local")

    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dataset_size": len(samples),
        "labeled_size": len(labeled),
        "classification_accuracy": classification.accuracy,
        "per_class_accuracy": classification.per_class_accuracy(),
        "repair_accuracy": repair.accuracy,
        "repair_validation_pass_rate": repair.validation_pass_rate,
        "hallucination_rate": classification.hallucination_rate,
        "latency_ms": classification.latency_percentiles(),
        "cost_gpt4o_mini_per_1k": cost_gpt["cost_per_1k_records_usd"],
        "cost_llama3_per_1k": cost_llama["cost_per_1k_records_usd"],
        "prompt_version": prompt_version,
    }

    if adversarial:
        results["adversarial"] = adversarial.to_dict()

    _log_to_mlflow(results, experiment_name, use_coordinator, dataset_path)

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Run DataSentinel eval harness")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--experiment", default="datasentinel-eval")
    parser.add_argument("--prompt-version", default=None)
    parser.add_argument("--coordinator", action="store_true", help="Use full coordinator (slower)")
    parser.add_argument("--no-adversarial", action="store_true")
    parser.add_argument("--json", action="store_true", help="Print results as JSON")
    args = parser.parse_args()

    results = run_eval(
        dataset_path=args.dataset,
        experiment_name=args.experiment,
        prompt_version=args.prompt_version,
        use_coordinator=args.coordinator,
        run_adversarial=not args.no_adversarial,
    )

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print("=== DataSentinel Eval Results ===")
        print(f"Dataset size:        {results['dataset_size']}")
        print(f"Classification acc:  {results['classification_accuracy']:.1%}")
        print(f"Repair accuracy:     {results['repair_accuracy']:.1%}")
        print(f"Hallucination rate:  {results['hallucination_rate']:.1%}")
        print(f"Latency p50/p95:     {results['latency_ms']['p50']}ms / {results['latency_ms']['p95']}ms")
        print(f"Cost GPT-4o-mini:    ${results['cost_gpt4o_mini_per_1k']}/1K records")
        print(f"Cost Llama 3 local:  ${results['cost_llama3_per_1k']}/1K records")
        if "adversarial" in results:
            print(f"Adversarial passed:  {results['adversarial']['passed']}")
        print(f"\nMLflow runs: file://{MLRUNS_DIR}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
