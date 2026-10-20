"""SLA snapshot + Slack cooldown for the dashboard API."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from dashboard.api.db import execute, fetch_one
from validation.contract import sla_targets
from validation.sla import evaluate_sla

logger = logging.getLogger(__name__)

SLA_ALERT_COOLDOWN_MINUTES = int(os.getenv("SLA_ALERT_COOLDOWN_MINUTES", "15"))


def current_sla() -> dict:
    targets = sla_targets()
    row = fetch_one(
        """
        SELECT
            count(*) FILTER (WHERE is_valid) AS valid_count,
            count(*) FILTER (WHERE NOT is_valid) AS invalid_count,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95_ms
        FROM validation_events
        WHERE time > now() - interval '24 hours'
        """
    ) or {}
    result = evaluate_sla(
        valid_count=int(row.get("valid_count") or 0),
        invalid_count=int(row.get("invalid_count") or 0),
        p95_latency_ms=float(row.get("p95_ms") or 0),
        max_failure_rate_pct=targets["max_failure_rate_pct"],
        p95_budget_ms=targets["p95_validation_latency_ms"],
    )
    _maybe_alert(result)
    return result


def _maybe_alert(result: dict) -> None:
    webhook = os.getenv("SLACK_WEBHOOK_URL", "").strip()
    if not webhook or not result["breached"]:
        return
    for name, fired, detail in (
        (
            "failure_rate",
            result["failure_rate_breached"],
            f"failure rate {result['failure_rate_pct']}% > {result['max_failure_rate_pct']}%",
        ),
        (
            "p95_latency",
            result["latency_breached"],
            f"p95 {result['p95_latency_ms']}ms > {result['p95_budget_ms']}ms",
        ),
    ):
        if fired and _should_alert(name):
            _post_slack(webhook, f"DataSentinel SLA breach ({name}): {detail} (24h window)")


def _should_alert(sla_name: str) -> bool:
    row = fetch_one(
        "SELECT last_status, last_alerted_at FROM sla_alert_state WHERE sla_name = %s",
        (sla_name,),
    )
    now = datetime.now(timezone.utc)
    if row and row.get("last_alerted_at"):
        last = row["last_alerted_at"]
        if getattr(last, "tzinfo", None) is None:
            last = last.replace(tzinfo=timezone.utc)
        age_min = (now - last).total_seconds() / 60
        if row.get("last_status") == "breached" and age_min < SLA_ALERT_COOLDOWN_MINUTES:
            return False
    execute(
        """
        INSERT INTO sla_alert_state (sla_name, last_status, last_alerted_at)
        VALUES (%s, 'breached', now())
        ON CONFLICT (sla_name) DO UPDATE
        SET last_status = 'breached', last_alerted_at = now()
        """,
        (sla_name,),
    )
    return True


def _post_slack(webhook: str, text: str) -> None:
    try:
        import requests

        requests.post(webhook, json={"text": text}, timeout=5)
    except Exception as exc:
        logger.warning("SLA Slack alert failed: %s", exc)
