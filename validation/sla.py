"""Contract SLA evaluation (failure rate and p95 validation latency)."""

from __future__ import annotations

from typing import Sequence


def p95(latencies_ms: Sequence[float]) -> float:
    if not latencies_ms:
        return 0.0
    ordered = sorted(float(v) for v in latencies_ms)
    idx = min(int(len(ordered) * 0.95), len(ordered) - 1)
    return round(ordered[idx], 2)


def evaluate_sla(
    *,
    valid_count: int,
    invalid_count: int,
    latencies_ms: Sequence[float] | None = None,
    p95_latency_ms: float | None = None,
    max_failure_rate_pct: float = 2.0,
    p95_budget_ms: float = 500.0,
) -> dict:
    total = int(valid_count) + int(invalid_count)
    failure_rate = round(100.0 * invalid_count / total, 3) if total else 0.0
    p95_ms = float(p95_latency_ms) if p95_latency_ms is not None else p95(latencies_ms or [])
    failure_breached = total > 0 and failure_rate > max_failure_rate_pct
    latency_breached = total > 0 and p95_ms > p95_budget_ms
    failed_bits = []
    ok_bits = []
    fail_msg = (
        f"{invalid_count} of {total} records failed ({failure_rate}% vs {max_failure_rate_pct}% budget)"
        if total
        else "no records in window"
    )
    lat_msg = f"p95 latency {p95_ms}ms vs {p95_budget_ms}ms budget"
    (failed_bits if failure_breached else ok_bits).append(fail_msg)
    (failed_bits if latency_breached else ok_bits).append(lat_msg)
    if failure_breached or latency_breached:
        headline = "SLA miss: " + "; ".join(failed_bits)
    else:
        headline = "SLAs healthy"
    return {
        "window": "24h",
        "valid_count": int(valid_count),
        "invalid_count": int(invalid_count),
        "total_count": total,
        "failure_rate_pct": failure_rate,
        "max_failure_rate_pct": float(max_failure_rate_pct),
        "failure_rate_breached": failure_breached,
        "p95_latency_ms": p95_ms,
        "p95_budget_ms": float(p95_budget_ms),
        "latency_breached": latency_breached,
        "breached": failure_breached or latency_breached,
        "headline": headline,
        "ok_detail": "; ".join(ok_bits),
    }
