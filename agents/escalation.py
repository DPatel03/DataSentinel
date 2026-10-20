"""Human Escalation agent — Slack + review queue."""

from __future__ import annotations

import json
import logging

import psycopg2
import requests
from pydantic import BaseModel
from agents.config import SLACK_WEBHOOK_URL
from agents.llm_client import LLMClient
from agents.models import ClassificationResult, DLQPayload
from agents.agent_outputs import EscalationResult

logger = logging.getLogger(__name__)


class _EscalationLLMOutput(BaseModel):
    summary: str
    recommended_action: str


class EscalationAgent:
    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()

    def escalate(
        self,
        payload: DLQPayload,
        classification: ClassificationResult,
        record_key: str,
        db_dsn: str,
    ) -> EscalationResult:
        if self.llm.mock:
            result = self._mock_escalation(payload, classification)
        else:
            try:
                llm_input = {**payload.model_dump(), "classification": classification.model_dump()}
                llm_out = self.llm.complete_json("escalation", llm_input, _EscalationLLMOutput)
                result = EscalationResult(
                    summary=llm_out.summary,
                    recommended_action=llm_out.recommended_action,
                    status="open",
                )
            except Exception as exc:
                logger.warning("Escalation LLM failed: %s", exc)
                result = self._mock_escalation(payload, classification)

        review_id = self._write_review_queue(db_dsn, record_key, payload, classification, result)
        result.review_queue_id = review_id
        result.slack_sent = self._notify_slack(payload, classification, result, record_key)
        result.status = "open"
        return result

    def _mock_escalation(
        self, payload: DLQPayload, classification: ClassificationResult
    ) -> EscalationResult:
        field = classification.affected_field or "unknown"
        return EscalationResult(
            summary=(
                f"Data quality failure on {field}: {classification.explanation} "
                f"(rule={payload.rule_violated}, class={classification.failure_class.value})"
            ),
            recommended_action=classification.suggested_fix or "Manual review required",
            status="open",
        )

    def _write_review_queue(
        self,
        dsn: str,
        record_key: str,
        payload: DLQPayload,
        classification: ClassificationResult,
        escalation: EscalationResult,
    ) -> int | None:
        try:
            with psycopg2.connect(dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO review_queue (
                            created_at, record_key, failure_class, confidence,
                            rule_violated, summary, recommended_action,
                            status, record_payload, classification_payload
                        ) VALUES (now(), %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                        RETURNING id
                        """,
                        (
                            record_key,
                            classification.failure_class.value,
                            classification.confidence,
                            payload.rule_violated,
                            escalation.summary,
                            escalation.recommended_action,
                            "open",
                            json.dumps(payload.record, default=str),
                            json.dumps(classification.model_dump(), default=str),
                        ),
                    )
                    row = cur.fetchone()
                conn.commit()
            return row[0] if row else None
        except Exception as exc:
            logger.warning("Failed to write review_queue: %s", exc)
            return None

    def _notify_slack(
        self,
        payload: DLQPayload,
        classification: ClassificationResult,
        escalation: EscalationResult,
        record_key: str,
    ) -> bool:
        text = (
            f":warning: *DataSentinel review needed*\n"
            f"*Key:* {record_key}\n"
            f"*Class:* {classification.failure_class.value} ({classification.confidence:.0%})\n"
            f"*Rule:* {payload.rule_violated}\n"
            f"*Summary:* {escalation.summary}\n"
            f"*Action:* {escalation.recommended_action}"
        )

        if not SLACK_WEBHOOK_URL:
            logger.info("Slack not configured — escalation logged:\n%s", text)
            return False

        try:
            response = requests.post(
                SLACK_WEBHOOK_URL,
                json={"text": text},
                timeout=5,
            )
            response.raise_for_status()
            return True
        except Exception as exc:
            logger.warning("Slack notification failed: %s", exc)
            return False
