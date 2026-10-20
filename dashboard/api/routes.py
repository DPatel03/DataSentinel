"""FastAPI route handlers for DataSentinel dashboard."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dashboard.api.db import execute, fetch_all, fetch_one
from dashboard.api.sla import current_sla

router = APIRouter()
ROOT = Path(__file__).resolve().parents[2]
MLRUNS = ROOT / "mlruns"


@router.get("/")
def api_root() -> dict:
    return {"message": "DataSentinel Dashboard API", "docs": "/docs"}


@router.get("/health")
def health() -> dict:
    db_ok = fetch_one("SELECT 1 AS ok") is not None
    return {
        "status": "ok" if db_ok else "degraded",
        "service": "datasentinel-dashboard",
        "database": db_ok,
    }


@router.get("/stats/overview")
def overview() -> dict:
    breaches = fetch_one(
        """
        SELECT count(*) AS total_breaches,
               count(DISTINCT rule_name) AS unique_rules
        FROM contract_breaches
        WHERE time > now() - interval '24 hours'
        """
    ) or {"total_breaches": 0, "unique_rules": 0}

    triage = fetch_one(
        """
        SELECT count(*) AS total_triaged,
               round(avg(confidence)::numeric, 3) AS avg_confidence
        FROM triage_events
        WHERE time > now() - interval '24 hours'
        """
    ) or {"total_triaged": 0, "avg_confidence": 0}

    repairs = fetch_one(
        """
        SELECT count(*) AS total_repairs,
               round(100.0 * avg(CASE WHEN validation_passed THEN 1.0 ELSE 0.0 END), 1) AS success_rate
        FROM repair_attempts
        WHERE time > now() - interval '24 hours'
        """
    ) or {"total_repairs": 0, "success_rate": 0}

    llm_cost = fetch_one(
        """
        SELECT coalesce(sum(cost_usd), 0) AS total_cost,
               count(*) AS total_calls
        FROM llm_traces
        WHERE time > now() - interval '24 hours'
        """
    ) or {"total_cost": 0, "total_calls": 0}

    return {
        "breaches_24h": int(breaches.get("total_breaches", 0)),
        "unique_rules_24h": int(breaches.get("unique_rules", 0)),
        "triaged_24h": int(triage.get("total_triaged", 0)),
        "avg_confidence_24h": float(triage.get("avg_confidence") or 0),
        "repairs_24h": int(repairs.get("total_repairs", 0)),
        "repair_success_rate_24h": float(repairs.get("success_rate") or 0),
        "llm_cost_24h_usd": float(llm_cost.get("total_cost") or 0),
        "llm_calls_24h": int(llm_cost.get("total_calls", 0)),
        "sla": current_sla(),
    }


@router.get("/stats/failure-rate")
def failure_rate() -> list[dict]:
    return fetch_all(
        """
        SELECT rule_name, field_name, sum(failure_count) AS failures
        FROM contract_breaches
        WHERE time > now() - interval '24 hours'
        GROUP BY rule_name, field_name
        ORDER BY failures DESC
        LIMIT 20
        """
    )


@router.get("/stats/triage-accuracy")
def triage_accuracy() -> list[dict]:
    return fetch_all(
        """
        SELECT date_trunc('hour', time) AS hour,
               failure_class,
               count(*) AS count,
               round(avg(confidence)::numeric, 3) AS avg_confidence
        FROM triage_events
        WHERE time > now() - interval '24 hours'
        GROUP BY 1, failure_class
        ORDER BY hour DESC
        """
    )


@router.get("/stats/repair-success")
def repair_success() -> list[dict]:
    return fetch_all(
        """
        SELECT field_repaired,
               validation_passed,
               routed_to_repaired,
               count(*) AS count
        FROM repair_attempts
        WHERE time > now() - interval '24 hours'
        GROUP BY field_repaired, validation_passed, routed_to_repaired
        ORDER BY count DESC
        """
    )


@router.get("/prompts/versions")
def prompt_versions() -> list[dict]:
    return fetch_all(
        """
        SELECT agent_name, prompt_id, version, is_active, accuracy, created_at
        FROM prompt_versions
        ORDER BY agent_name, version DESC
        """
    )


@router.get("/prompts/eval-runs")
def prompt_eval_runs() -> list[dict]:
    return fetch_all(
        """
        SELECT time, agent_name, prompt_id, accuracy, passed
        FROM prompt_eval_runs
        ORDER BY time DESC
        LIMIT 50
        """
    )


@router.get("/prompts/diff/{agent_name}")
def prompt_diff(agent_name: str) -> dict:
    versions = fetch_all(
        """
        SELECT version, prompt_text, accuracy, is_active
        FROM prompt_versions
        WHERE agent_name = %s
        ORDER BY version DESC
        LIMIT 2
        """,
        (agent_name,),
    )
    if len(versions) < 2:
        return {"agent_name": agent_name, "diff": None, "versions": versions}
    v_new, v_old = versions[0], versions[1]
    return {
        "agent_name": agent_name,
        "new_version": v_new["version"],
        "old_version": v_old["version"],
        "accuracy_delta": (v_new.get("accuracy") or 0) - (v_old.get("accuracy") or 0),
        "new_text": v_new["prompt_text"][:500],
        "old_text": v_old["prompt_text"][:500],
        "versions": versions,
    }


@router.get("/stats/sla")
def sla_status() -> dict:
    return current_sla()


@router.get("/breaches")
def recent_breaches(limit: int = 25) -> list[dict]:
    return fetch_all(
        """
        SELECT time, record_key, rule_name, field_name, contract_version, sample_record
        FROM contract_breaches
        ORDER BY time DESC
        LIMIT %s
        """,
        (limit,),
    )


@router.get("/records/{record_key:path}")
def record_detail(record_key: str) -> dict:
    breach = fetch_one(
        """
        SELECT time, record_key, rule_name, field_name, contract_version, sample_record
        FROM contract_breaches
        WHERE record_key = %s
        ORDER BY time DESC
        LIMIT 1
        """,
        (record_key,),
    )
    triage = fetch_one(
        """
        SELECT time, record_key, rule_violated, failure_class, confidence, explanation,
               affected_field, requires_human_review, classifier_source, raw_payload
        FROM triage_events
        WHERE record_key = %s
        ORDER BY time DESC
        LIMIT 1
        """,
        (record_key,),
    )
    repair = fetch_one(
        """
        SELECT time, record_key, original_record, repaired_record, field_repaired,
               confidence, validation_passed, routed_to_repaired
        FROM repair_attempts
        WHERE record_key = %s
        ORDER BY time DESC
        LIMIT 1
        """,
        (record_key,),
    )
    review = fetch_one(
        """
        SELECT id, created_at, record_key, failure_class, confidence, rule_violated,
               summary, recommended_action, status, record_payload, classification_payload,
               human_label, human_note, resolved_by, resolved_at
        FROM review_queue
        WHERE record_key = %s
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (record_key,),
    )
    raw = (triage or {}).get("raw_payload") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {}
    good_samples = raw.get("sample_good_records") or []
    record = (
        (breach or {}).get("sample_record")
        or (review or {}).get("record_payload")
        or raw.get("record")
        or ((repair or {}).get("original_record"))
    )
    if not any((breach, triage, repair, review)):
        raise HTTPException(status_code=404, detail="Record not found")
    return {
        "record_key": record_key,
        "record": record,
        "good_samples": good_samples,
        "breach": breach,
        "triage": triage,
        "repair": repair,
        "review": review,
    }


@router.get("/review-queue")
def review_queue(status: str | None = None) -> list[dict]:
    if status:
        return fetch_all(
            """
            SELECT id, created_at, record_key, failure_class, confidence,
                   rule_violated, summary, recommended_action, status,
                   human_label, human_note
            FROM review_queue
            WHERE status = %s
            ORDER BY created_at DESC
            LIMIT 100
            """,
            (status,),
        )
    return fetch_all(
        """
        SELECT id, created_at, record_key, failure_class, confidence,
               rule_violated, summary, recommended_action, status,
               human_label, human_note
        FROM review_queue
        ORDER BY created_at DESC
        LIMIT 100
        """
    )


class ReviewUpdate(BaseModel):
    status: str = Field(default="resolved", pattern="^(open|resolved|dismissed|accepted|rejected)$")
    resolved_by: str = "dashboard"
    human_label: str | None = None
    human_note: str | None = None


@router.patch("/review-queue/{item_id}")
def update_review(item_id: int, body: ReviewUpdate) -> dict:
    rowcount = execute(
        """
        UPDATE review_queue
        SET status = %s,
            resolved_by = %s,
            human_label = COALESCE(%s, human_label),
            human_note = COALESCE(%s, human_note),
            resolved_at = CASE WHEN %s = 'open' THEN NULL ELSE now() END,
            updated_at = now()
        WHERE id = %s
        """,
        (body.status, body.resolved_by, body.human_label, body.human_note, body.status, item_id),
    )
    if rowcount == 0:
        raise HTTPException(status_code=404, detail="Review item not found")
    return {
        "id": item_id,
        "status": body.status,
        "resolved_by": body.resolved_by,
        "human_label": body.human_label,
        "human_note": body.human_note,
    }


@router.get("/llm/traces")
def llm_traces(limit: int = 50) -> list[dict]:
    return fetch_all(
        """
        SELECT time, trace_id, agent_name, model, prompt_version,
               input_tokens, output_tokens, latency_ms, cost_usd, success,
               left(input_preview, 200) AS input_preview,
               left(output_preview, 200) AS output_preview
        FROM llm_traces
        ORDER BY time DESC
        LIMIT %s
        """,
        (limit,),
    )


def latest_eval_file(mlruns: Path) -> Path | None:
    """Pick the newest eval snapshot (MLflow artifact or timestamped fallback)."""
    if not mlruns.exists():
        return None
    files = [p for p in mlruns.rglob("eval_results.json") if p.is_file()]
    files.extend(p for p in mlruns.glob("eval_*.json") if p.is_file())
    if not files:
        return None
    return max(files, key=lambda path: path.stat().st_mtime)


@router.get("/eval/latest")
def latest_eval() -> dict:
    """Return latest eval results if available."""
    results_file = latest_eval_file(MLRUNS)
    if not results_file:
        return {"available": False}
    try:
        return {"available": True, "results": json.loads(results_file.read_text())}
    except (OSError, json.JSONDecodeError):
        return {"available": False}
