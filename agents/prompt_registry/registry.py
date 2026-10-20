"""Prompt version registry with eval and auto-rollback."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor

from agents.config import OPENAI_API_KEY, PROMPT_ACCURACY_THRESHOLD, PROMPT_EVAL_SAMPLE_SIZE, SLACK_WEBHOOK_URL
from agents.heuristics import classify_heuristic
from agents.models import ClassificationResult, DLQPayload, FailureClass
from validation.config import timescaledb_dsn

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
LABELED_DATA = Path(__file__).resolve().parent / "labeled_data.json"
FULL_DATASET = Path(__file__).resolve().parents[2] / "eval" / "dataset" / "full_dataset.json"

AGENT_PROMPTS = ("classifier", "repair", "schema_evolution", "anomaly", "escalation")


class PromptRegistry:
    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn or timescaledb_dsn()

    def seed_from_files(self) -> None:
        """Load file prompts into DB if no versions exist."""
        with psycopg2.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                for agent in AGENT_PROMPTS:
                    cur.execute(
                        "SELECT count(*) FROM prompt_versions WHERE agent_name = %s",
                        (agent,),
                    )
                    if cur.fetchone()[0] > 0:
                        continue
                    path = PROMPTS_DIR / f"{agent}.txt"
                    if not path.exists():
                        continue
                    text = path.read_text()
                    cur.execute(
                        """
                        INSERT INTO prompt_versions (
                            prompt_id, agent_name, version, prompt_text,
                            created_at, is_active, accuracy
                        ) VALUES (%s, %s, 1, %s, %s, TRUE, NULL)
                        """,
                        (f"{agent}_v1", agent, text, datetime.now(timezone.utc)),
                    )
                    logger.info("Seeded prompt %s v1", agent)
            conn.commit()

    def get_active_prompt(self, agent_name: str) -> str:
        with psycopg2.connect(self.dsn) as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT prompt_text FROM prompt_versions
                    WHERE agent_name = %s AND is_active = TRUE
                    ORDER BY version DESC LIMIT 1
                    """,
                    (agent_name,),
                )
                row = cur.fetchone()
        if row:
            return row["prompt_text"]
        path = PROMPTS_DIR / f"{agent_name}.txt"
        return path.read_text() if path.exists() else ""

    def register_version(self, agent_name: str, prompt_text: str) -> dict:
        """Register a new prompt version. Activate only if eval passes."""
        accuracy: float | None = None
        eval_method: str | None = None
        passed = True
        if agent_name == "classifier":
            accuracy, eval_method = self.evaluate_classifier(prompt_text)
            passed = accuracy >= PROMPT_ACCURACY_THRESHOLD

        with psycopg2.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COALESCE(max(version), 0) FROM prompt_versions WHERE agent_name = %s",
                    (agent_name,),
                )
                next_version = cur.fetchone()[0] + 1
                prompt_id = f"{agent_name}_v{next_version}"

                cur.execute(
                    """
                    INSERT INTO prompt_versions (
                        prompt_id, agent_name, version, prompt_text,
                        created_at, is_active, accuracy
                    ) VALUES (%s, %s, %s, %s, %s, FALSE, %s)
                    RETURNING id
                    """,
                    (
                        prompt_id,
                        agent_name,
                        next_version,
                        prompt_text,
                        datetime.now(timezone.utc),
                        accuracy,
                    ),
                )
                new_id = cur.fetchone()[0]
                cur.execute(
                    """
                    INSERT INTO prompt_eval_runs (time, agent_name, prompt_id, accuracy, passed)
                    VALUES (now(), %s, %s, %s, %s)
                    """,
                    (agent_name, prompt_id, accuracy, passed),
                )

                rolled_back = not passed
                if passed:
                    cur.execute(
                        "UPDATE prompt_versions SET is_active = FALSE WHERE agent_name = %s",
                        (agent_name,),
                    )
                    cur.execute(
                        "UPDATE prompt_versions SET is_active = TRUE WHERE id = %s",
                        (new_id,),
                    )
                else:
                    self._alert_rollback(agent_name, prompt_id, accuracy or 0.0)
            conn.commit()

        return {
            "prompt_id": prompt_id,
            "version": next_version,
            "accuracy": accuracy,
            "passed": passed,
            "rolled_back": rolled_back,
            "eval_method": eval_method,
        }

    def evaluate_classifier_prompt(self, prompt_text: str | None = None) -> float:
        accuracy, _method = self.evaluate_classifier(prompt_text)
        return accuracy

    def evaluate_classifier(self, prompt_text: str | None = None) -> tuple[float, str]:
        """Score a classifier prompt. Uses a live LLM held-out slice when an API key is set."""
        heuristic_acc = self._heuristic_accuracy()
        if prompt_text and OPENAI_API_KEY:
            try:
                llm_acc = self._llm_held_out_accuracy(prompt_text)
                return llm_acc, "llm_held_out"
            except Exception as exc:
                logger.warning("LLM prompt eval failed, using heuristic gate: %s", exc)
        return heuristic_acc, "heuristic_labeled_set"

    def _load_labeled_samples(self) -> list[dict]:
        dataset_path = FULL_DATASET if FULL_DATASET.exists() else LABELED_DATA
        if not dataset_path.exists():
            return []
        samples = json.loads(dataset_path.read_text())
        return [s for s in samples if s.get("expected_class") not in ("clean", None)]

    def _heuristic_accuracy(self) -> float:
        labeled = self._load_labeled_samples()
        if not labeled:
            return 1.0
        correct = 0
        for sample in labeled:
            payload = DLQPayload.model_validate(sample["payload"])
            expected = FailureClass(sample["expected_class"])
            predicted = classify_heuristic(payload).failure_class
            if predicted == expected:
                correct += 1
        return round(correct / len(labeled), 4)

    def _llm_held_out_accuracy(self, prompt_text: str) -> float:
        """Run the candidate prompt on a small held-out slice (cost-capped)."""
        from agents.llm_client import LLMClient

        labeled = self._load_labeled_samples()
        if not labeled:
            return 1.0
        step = max(1, len(labeled) // PROMPT_EVAL_SAMPLE_SIZE)
        held_out = labeled[::step][:PROMPT_EVAL_SAMPLE_SIZE]
        client = LLMClient()
        if client.mock:
            return self._heuristic_accuracy()

        correct = 0
        for sample in held_out:
            payload = DLQPayload.model_validate(sample["payload"])
            result = client.complete_json(
                "classifier",
                payload.model_dump(),
                ClassificationResult,
                system_prompt=prompt_text,
            )
            if result.failure_class.value == sample["expected_class"]:
                correct += 1
        return round(correct / len(held_out), 4)

    def list_versions(self, agent_name: str) -> list[dict]:
        with psycopg2.connect(self.dsn) as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT prompt_id, version, is_active, accuracy, created_at
                    FROM prompt_versions WHERE agent_name = %s
                    ORDER BY version DESC
                    """,
                    (agent_name,),
                )
                return [dict(row) for row in cur.fetchall()]

    def _alert_rollback(self, agent_name: str, prompt_id: str, accuracy: float) -> None:
        msg = (
            f":rotating_light: Prompt rollback: {agent_name} {prompt_id} "
            f"accuracy {accuracy:.0%} < {PROMPT_ACCURACY_THRESHOLD:.0%}"
        )
        logger.warning(msg)
        if not SLACK_WEBHOOK_URL:
            return
        try:
            import requests

            requests.post(SLACK_WEBHOOK_URL, json={"text": msg}, timeout=5)
        except Exception as exc:
            logger.warning("Rollback Slack alert failed: %s", exc)
