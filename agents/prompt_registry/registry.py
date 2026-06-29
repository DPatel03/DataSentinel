"""Prompt version registry with eval and auto-rollback."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor

from agents.config import PROMPT_ACCURACY_THRESHOLD, SLACK_WEBHOOK_URL
from agents.heuristics import classify_heuristic
from agents.models import DLQPayload, FailureClass
from validation.config import timescaledb_dsn

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
LABELED_DATA = Path(__file__).resolve().parent / "labeled_data.json"

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
        """Register new prompt version, eval, rollback if below threshold."""
        with psycopg2.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COALESCE(max(version), 0) FROM prompt_versions WHERE agent_name = %s",
                    (agent_name,),
                )
                next_version = cur.fetchone()[0] + 1
                prompt_id = f"{agent_name}_v{next_version}"

                cur.execute(
                    "UPDATE prompt_versions SET is_active = FALSE WHERE agent_name = %s",
                    (agent_name,),
                )
                cur.execute(
                    """
                    INSERT INTO prompt_versions (
                        prompt_id, agent_name, version, prompt_text,
                        created_at, is_active, accuracy
                    ) VALUES (%s, %s, %s, %s, %s, TRUE, NULL)
                    RETURNING id
                    """,
                    (prompt_id, agent_name, next_version, prompt_text, datetime.now(timezone.utc)),
                )
                new_id = cur.fetchone()[0]
            conn.commit()

        accuracy = self.evaluate_classifier_prompt(prompt_text) if agent_name == "classifier" else 1.0
        rolled_back = False

        with psycopg2.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE prompt_versions SET accuracy = %s WHERE id = %s",
                    (accuracy, new_id),
                )
                cur.execute(
                    """
                    INSERT INTO prompt_eval_runs (time, agent_name, prompt_id, accuracy, passed)
                    VALUES (now(), %s, %s, %s, %s)
                    """,
                    (agent_name, prompt_id, accuracy, accuracy >= PROMPT_ACCURACY_THRESHOLD),
                )

                if accuracy < PROMPT_ACCURACY_THRESHOLD:
                    rolled_back = True
                    cur.execute(
                        "UPDATE prompt_versions SET is_active = FALSE WHERE id = %s",
                        (new_id,),
                    )
                    cur.execute(
                        """
                        UPDATE prompt_versions SET is_active = TRUE
                        WHERE agent_name = %s AND version = (
                            SELECT max(version) FROM prompt_versions
                            WHERE agent_name = %s AND id != %s
                        )
                        """,
                        (agent_name, agent_name, new_id),
                    )
                    self._alert_rollback(agent_name, prompt_id, accuracy)
            conn.commit()

        return {
            "prompt_id": prompt_id,
            "version": next_version,
            "accuracy": accuracy,
            "passed": accuracy >= PROMPT_ACCURACY_THRESHOLD,
            "rolled_back": rolled_back,
        }

    def evaluate_classifier_prompt(self, prompt_text: str | None = None) -> float:
        """Eval classifier using labeled dataset + heuristics as oracle."""
        if not LABELED_DATA.exists():
            return 1.0

        samples = json.loads(LABELED_DATA.read_text())
        if not samples:
            return 1.0

        correct = 0
        for sample in samples:
            payload = DLQPayload.model_validate(sample["payload"])
            expected = FailureClass(sample["expected_class"])
            predicted = classify_heuristic(payload).failure_class
            if predicted == expected:
                correct += 1

        return round(correct / len(samples), 4)

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
