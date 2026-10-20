"""Tests for contract SLA evaluation."""

from __future__ import annotations

from validation.contract import sla_targets
from validation.sla import evaluate_sla, p95


def test_contract_sla_targets() -> None:
    targets = sla_targets()
    assert targets["max_failure_rate_pct"] == 2.0
    assert targets["p95_validation_latency_ms"] == 500


def test_failure_rate_breach() -> None:
    result = evaluate_sla(valid_count=90, invalid_count=10, latencies_ms=[5] * 100)
    assert result["failure_rate_pct"] == 10.0
    assert result["failure_rate_breached"] is True
    assert result["latency_breached"] is False
    assert result["breached"] is True
    assert "failure rate" in result["headline"].lower() or "failed" in result["headline"].lower()
    assert "p95" in result["ok_detail"]


def test_empty_window_is_not_a_breach() -> None:
    result = evaluate_sla(valid_count=0, invalid_count=0, latencies_ms=[])
    assert result["breached"] is False
    assert result["failure_rate_pct"] == 0.0


def test_p95_latency_breach() -> None:
    latencies = [10.0] * 19 + [800.0]
    result = evaluate_sla(
        valid_count=20,
        invalid_count=0,
        latencies_ms=latencies,
        p95_budget_ms=500,
    )
    assert p95(latencies) == 800.0
    assert result["latency_breached"] is True


def test_exact_budget_is_not_a_breach() -> None:
    result = evaluate_sla(valid_count=196, invalid_count=4, latencies_ms=[10] * 200)
    assert result["failure_rate_pct"] == 2.0
    assert result["failure_rate_breached"] is False
    assert result["breached"] is False
    assert result["headline"] == "SLAs healthy"
