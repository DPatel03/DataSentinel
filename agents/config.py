"""Agent configuration from environment."""

from __future__ import annotations

import os

from validation.config import load_env

load_env()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "3"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "2"))
HEURISTIC_CONFIDENCE_THRESHOLD = float(os.getenv("HEURISTIC_CONFIDENCE_THRESHOLD", "0.7"))
REPAIR_CONFIDENCE_THRESHOLD = float(os.getenv("REPAIR_CONFIDENCE_THRESHOLD", "0.6"))

DLQ_TOPIC = "taxi.rides.dead-letter"
REPAIRED_TOPIC = "taxi.rides.repaired"
ANOMALY_TOPIC = "taxi.rides.anomaly"

SCHEMA_REGISTRY_URL = os.getenv("SCHEMA_REGISTRY_URL", "http://localhost:8081")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")  # owner/repo
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
SCHEMA_EVOLUTION_CONFIDENCE_THRESHOLD = float(os.getenv("SCHEMA_EVOLUTION_CONFIDENCE_THRESHOLD", "0.85"))
PROMPT_ACCURACY_THRESHOLD = float(os.getenv("PROMPT_ACCURACY_THRESHOLD", "0.85"))
PROMPT_EVAL_SAMPLE_SIZE = int(os.getenv("PROMPT_EVAL_SAMPLE_SIZE", "15"))
