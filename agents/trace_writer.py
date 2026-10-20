"""LLM trace writer for dashboard observability."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import psycopg2

from validation.config import timescaledb_dsn

logger = logging.getLogger(__name__)

# gpt-4o-mini pricing (USD per 1M tokens)
INPUT_COST_PER_M = 0.15
OUTPUT_COST_PER_M = 0.60


def estimate_cost(input_tokens: int, output_tokens: int) -> float:
    return round(
        (input_tokens / 1_000_000 * INPUT_COST_PER_M)
        + (output_tokens / 1_000_000 * OUTPUT_COST_PER_M),
        6,
    )


def write_trace(
    *,
    agent_name: str,
    model: str,
    latency_ms: float,
    input_preview: str,
    output_preview: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    success: bool = True,
    prompt_version: str | None = None,
    trace_id: str | None = None,
) -> str:
    trace_id = trace_id or str(uuid.uuid4())
    cost = estimate_cost(input_tokens, output_tokens)

    try:
        with psycopg2.connect(timescaledb_dsn()) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO llm_traces (
                        time, trace_id, agent_name, model, prompt_version,
                        input_tokens, output_tokens, latency_ms, cost_usd,
                        success, input_preview, output_preview
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        datetime.now(timezone.utc),
                        trace_id,
                        agent_name,
                        model,
                        prompt_version,
                        input_tokens,
                        output_tokens,
                        latency_ms,
                        cost,
                        success,
                        input_preview[:2000],
                        output_preview[:2000],
                    ),
                )
            conn.commit()
    except Exception as exc:
        logger.debug("LLM trace write skipped: %s", exc)

    return trace_id
