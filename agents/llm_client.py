"""OpenAI client with timeout, retries, mock fallback, and trace logging."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from agents.config import (
    LLM_MAX_RETRIES,
    LLM_TIMEOUT_SECONDS,
    OPENAI_API_KEY,
    OPENAI_MODEL,
)
from agents.trace_writer import write_trace

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

    def complete_json(
        self,
        prompt_name: str,
        user_payload: dict[str, Any],
        model_type: type[T],
        system_prompt: str | None = None,
    ) -> T:
        start = time.perf_counter()
        if self.mock:
            data = _mock_json_response(prompt_name, user_payload)
            result = model_type.model_validate(data)
            write_trace(
                agent_name=prompt_name,
                model="mock",
                latency_ms=(time.perf_counter() - start) * 1000,
                input_preview=json.dumps(user_payload, default=str)[:500],
                output_preview=json.dumps(data)[:500],
                success=True,
            )
            return result

        system_prompt = system_prompt or load_prompt(prompt_name)
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

                usage = getattr(response, "usage", None)
                input_tokens = getattr(usage, "prompt_tokens", 0) or 0
                output_tokens = getattr(usage, "completion_tokens", 0) or 0
                trace_id = write_trace(
                    agent_name=prompt_name,
                    model=OPENAI_MODEL,
                    latency_ms=(time.perf_counter() - start) * 1000,
                    input_preview=user_content[:500],
                    output_preview=content[:500],
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    success=True,
                )
                self._maybe_langfuse(prompt_name, system_prompt, user_content, content, trace_id, input_tokens, output_tokens)
                return result
            except Exception as exc:
                last_error = exc
                logger.warning("LLM attempt %s failed: %s", attempt, exc)

        write_trace(
            agent_name=prompt_name,
            model=OPENAI_MODEL,
            latency_ms=(time.perf_counter() - start) * 1000,
            input_preview=user_content[:500],
            output_preview=str(last_error)[:500],
            success=False,
        )
        raise RuntimeError(f"LLM failed after {LLM_MAX_RETRIES} retries: {last_error}")

    def _maybe_langfuse(
        self,
        prompt_name: str,
        system_prompt: str,
        user_content: str,
        output: str,
        trace_id: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        """Optional Langfuse integration when keys are configured."""
        public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "")
        secret_key = os.getenv("LANGFUSE_SECRET_KEY", "")
        host = os.getenv("LANGFUSE_HOST", "http://localhost:3100")
        if not public_key or not secret_key:
            return
        try:
            from langfuse import Langfuse

            lf = Langfuse(public_key=public_key, secret_key=secret_key, host=host)
            trace = lf.trace(id=trace_id, name=prompt_name)
            trace.generation(
                name=f"{prompt_name}_completion",
                model=OPENAI_MODEL,
                input=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}],
                output=output,
                usage={"input": input_tokens, "output": output_tokens},
            )
            lf.flush()
        except Exception as exc:
            logger.debug("Langfuse trace skipped: %s", exc)
