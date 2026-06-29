"""OpenAI client with timeout, retries, and mock fallback."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from agents.config import (
    LLM_MAX_RETRIES,
    LLM_TIMEOUT_SECONDS,
    OPENAI_API_KEY,
    OPENAI_MODEL,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def load_prompt(name: str) -> str:
    try:
        from agents.prompt_registry.registry import PromptRegistry

        text = PromptRegistry().get_active_prompt(name)
        if text:
            return text
    except Exception:
        pass
    return (PROMPTS_DIR / f"{name}.txt").read_text()


def _mock_json_response(prompt_name: str, user_payload: dict[str, Any]) -> dict[str, Any]:
    """Deterministic mock responses when no API key is configured."""
    record = user_payload.get("record") or {}
    rule = user_payload.get("rule_violated", "")

    if prompt_name == "classifier":
        from agents.heuristics import classify_heuristic
        from agents.models import DLQPayload

        payload = DLQPayload.model_validate(user_payload)
        result = classify_heuristic(payload)
        return result.model_dump()

    if prompt_name == "repair":
        fare = record.get("fare_amount")
        repaired = dict(record)
        field = None
        explanation = "Mock repair: no changes"
        confidence = 0.5

        if rule == "fare_amount_range" and fare is not None and float(fare) < 0:
            repaired["fare_amount"] = abs(float(fare))
            field = "fare_amount"
            explanation = f"Mock repair: abs(fare_amount) -> {repaired['fare_amount']}"
            confidence = 0.85
        elif rule == "dropoff_after_pickup":
            pickup = record.get("pickup_datetime")
            dropoff = record.get("dropoff_datetime")
            if pickup and dropoff:
                repaired["pickup_datetime"], repaired["dropoff_datetime"] = dropoff, pickup
                field = "dropoff_datetime"
                explanation = "Mock repair: swapped pickup and dropoff"
                confidence = 0.88

        return {
            "repaired_record": repaired,
            "field_repaired": field,
            "confidence": confidence,
            "explanation": explanation,
        }

    if prompt_name == "schema_evolution":
        record = user_payload.get("record") or {}
        version = "v2" if record.get("congestion_surcharge") is not None else "v1"
        return {
            "detected_schema_version": version,
            "drift_description": f"Mock schema drift analysis for {version}",
            "affected_fields": ["congestion_surcharge"] if version == "v2" else ["schema_version"],
            "ge_suite_code": "# mock GE suite",
            "contract_suggestion": "Update contract for v2 fields",
            "confidence": 0.88,
            "registry_updated": False,
            "github_issue_url": None,
            "github_issue_number": None,
        }

    if prompt_name == "anomaly":
        record = dict(user_payload.get("record") or {})
        return {
            "record": record,
            "explanation": "Mock anomaly: value outside expected operational range.",
            "severity": 4,
            "suggested_action": "Flag and exclude from aggregates",
            "matched_known_pattern": False,
            "pattern_name": None,
            "reclassified_from": None,
            "routed_to_anomaly": False,
        }

    if prompt_name == "escalation":
        classification = user_payload.get("classification", {})
        return {
            "summary": f"Mock escalation for {classification.get('failure_class', 'unknown')}",
            "recommended_action": "Review manually",
            "status": "open",
        }

    return {}


class LLMClient:
    def __init__(self, mock: bool = False) -> None:
        self.mock = mock or not OPENAI_API_KEY
        self._client = None
        if not self.mock:
            from openai import OpenAI

            self._client = OpenAI(api_key=OPENAI_API_KEY, timeout=LLM_TIMEOUT_SECONDS)

    def complete_json(self, prompt_name: str, user_payload: dict[str, Any], model_type: type[T]) -> T:
        if self.mock:
            data = _mock_json_response(prompt_name, user_payload)
            return model_type.model_validate(data)

        system_prompt = load_prompt(prompt_name)
        user_content = json.dumps(user_payload, default=str)

        last_error: Exception | None = None
        for attempt in range(1, LLM_MAX_RETRIES + 1):
            try:
                response = self._client.chat.completions.create(
                    model=OPENAI_MODEL,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                    timeout=LLM_TIMEOUT_SECONDS,
                )
                content = response.choices[0].message.content or "{}"
                data = json.loads(content)
                result = model_type.model_validate(data)
                if hasattr(result, "model_copy"):
                    try:
                        result = result.model_copy(update={"source": "llm"})
                    except Exception:
                        pass
                return result
            except Exception as exc:
                last_error = exc
                logger.warning("LLM attempt %s failed: %s", attempt, exc)

        raise RuntimeError(f"LLM failed after {LLM_MAX_RETRIES} retries: {last_error}")
