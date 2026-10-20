"""Schema Evolution agent — handles schema_drift failures."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import requests
from confluent_kafka.schema_registry import Schema, SchemaRegistryClient

from agents.config import (
    GITHUB_REPO,
    GITHUB_TOKEN,
    SCHEMA_EVOLUTION_CONFIDENCE_THRESHOLD,
    SCHEMA_REGISTRY_URL,
)
from agents.llm_client import LLMClient
from agents.models import ClassificationResult, DLQPayload
from agents.agent_outputs import SchemaEvolutionResult

logger = logging.getLogger(__name__)

SCHEMAS_DIR = Path(__file__).resolve().parents[1] / "ingestion" / "schemas"
RAW_SUBJECT = "taxi.rides.raw-value"


class _SchemaEvolutionLLMOutput(SchemaEvolutionResult):
    pass


def _detect_schema_version(record: dict | None) -> str:
    if not record:
        return "unknown"
    if record.get("schema_version"):
        return str(record["schema_version"])
    if "congestion_surcharge" in record:
        return "v2"
    pickup = record.get("pickup_datetime", "")
    if pickup and str(pickup)[:4] < "2020":
        return "v1"
    return "v2"


def _default_ge_suite(affected_fields: list[str]) -> str:
    checks = []
    for field in affected_fields or ["congestion_surcharge"]:
        checks.append(
            f'    suite.add_expectation('
            f'gx.expectations.ExpectColumnToExist(column="{field}"))'
        )
    body = "\n".join(checks) if checks else "    pass"
    return f'''"""Auto-generated expectation suite for schema drift."""
import great_expectations as gx

def build_drift_suite():
    context = gx.get_context(mode="ephemeral")
    suite = context.suites.add(gx.ExpectationSuite(name="schema_drift_suite"))
{body}
    return suite
'''


class SchemaEvolutionAgent:
    def __init__(self, llm: LLMClient | None = None, registry_url: str = SCHEMA_REGISTRY_URL) -> None:
        self.llm = llm or LLMClient()
        self.registry_url = registry_url

    def handle(self, payload: DLQPayload, classification: ClassificationResult) -> SchemaEvolutionResult:
        record = payload.record or {}
        detected = _detect_schema_version(record)

        if self.llm.mock:
            result = self._mock_result(payload, detected)
        else:
            try:
                llm_input = {**payload.model_dump(), "classification": classification.model_dump()}
                result = self.llm.complete_json("schema_evolution", llm_input, _SchemaEvolutionLLMOutput)
            except Exception as exc:
                logger.warning("Schema evolution LLM failed: %s", exc)
                result = self._mock_result(payload, detected)

        if result.confidence >= SCHEMA_EVOLUTION_CONFIDENCE_THRESHOLD:
            result.registry_updated = self._try_register_schema(detected)

        issue_url, issue_num = self._open_github_issue(result, payload)
        result.github_issue_url = issue_url
        result.github_issue_number = issue_num

        return result

    def _mock_result(self, payload: DLQPayload, detected: str) -> SchemaEvolutionResult:
        record = payload.record or {}
        affected = []
        if detected == "v2" and "congestion_surcharge" not in record:
            affected = ["congestion_surcharge"]
        elif payload.rule_violated == "avro_deserialization_failed":
            affected = ["schema_version"]

        return SchemaEvolutionResult(
            detected_schema_version=detected,
            drift_description=(
                f"Schema drift detected for {detected}. Rule violated: {payload.rule_violated}. "
                "Record may use pre/post-2020 TLC column set."
            ),
            affected_fields=affected or ["schema_version"],
            ge_suite_code=_default_ge_suite(affected),
            contract_suggestion=(
                "Add congestion_surcharge to contract fields with schema_versions: [v2]"
                if detected == "v2"
                else "Verify v1 fields match taxi-ride-v1.avsc"
            ),
            confidence=0.88,
        )

    def _try_register_schema(self, version: str) -> bool:
        schema_file = SCHEMAS_DIR / f"taxi-ride-{version}.avsc"
        if not schema_file.exists():
            logger.warning("Schema file not found: %s", schema_file)
            return False
        try:
            client = SchemaRegistryClient({"url": self.registry_url})
            schema_text = json.dumps(json.loads(schema_file.read_text()))
            schema_id = client.register_schema(RAW_SUBJECT, Schema(schema_text, "AVRO"))
            logger.info("Registered schema %s (id=%s)", version, schema_id)
            return True
        except Exception as exc:
            logger.warning("Schema registry update skipped: %s", exc)
            return False

    def _open_github_issue(
        self, result: SchemaEvolutionResult, payload: DLQPayload
    ) -> tuple[str | None, int | None]:
        if not GITHUB_TOKEN or not GITHUB_REPO:
            logger.info("GitHub not configured — writing issue to logs only")
            logger.info(
                "Would open issue: schema drift %s fields=%s",
                result.detected_schema_version,
                result.affected_fields,
            )
            return None, None

        title = f"[DataSentinel] Schema drift detected — {result.detected_schema_version}"
        body = (
            f"## Schema drift\n\n"
            f"{result.drift_description}\n\n"
            f"**Affected fields:** {', '.join(result.affected_fields)}\n\n"
            f"**Contract suggestion:**\n```\n{result.contract_suggestion}\n```\n\n"
            f"**Rule violated:** {payload.rule_violated}\n\n"
            f"**Sample record:**\n```json\n{json.dumps(payload.record, indent=2, default=str)}\n```\n\n"
            f"**GE suite:**\n```python\n{result.ge_suite_code[:2000]}\n```\n"
        )
        try:
            response = requests.post(
                f"https://api.github.com/repos/{GITHUB_REPO}/issues",
                headers={
                    "Authorization": f"Bearer {GITHUB_TOKEN}",
                    "Accept": "application/vnd.github+json",
                },
                json={"title": title, "body": body, "labels": ["schema-drift", "datasentinel"]},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("html_url"), data.get("number")
        except Exception as exc:
            logger.warning("GitHub issue creation failed: %s", exc)
            return None, None
