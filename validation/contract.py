"""YAML contract loading and per-record validation (no pandas dependency)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

CONTRACT_PATH = Path(__file__).resolve().parent / "contracts" / "v1.0.0.yaml"


def load_contract(path: Path | None = None) -> dict[str, Any]:
    contract_path = path or CONTRACT_PATH
    with contract_path.open() as handle:
        return yaml.safe_load(handle)


def _parse_ts(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def validate_record(
    record: dict[str, Any], contract: dict[str, Any] | None = None
) -> tuple[bool, str | None, str | None]:
    """Return (is_valid, rule_violated, field_name)."""
    contract = contract or load_contract()
    version = record.get("schema_version", "v1")

    for field, rules in contract["fields"].items():
        allowed_versions = rules.get("schema_versions")
        if allowed_versions and version not in allowed_versions:
            continue

        value = record.get(field)
        if value is None:
            if rules.get("nullable") is False:
                return False, f"{field}_not_null", field
            continue

        field_range = rules.get("range")
        if field_range and not (field_range[0] <= float(value) <= field_range[1]):
            return False, f"{field}_range", field

        allowed_values = rules.get("allowed_values")
        if allowed_values and int(value) not in allowed_values:
            return False, f"{field}_allowed_values", field

    pickup = _parse_ts(record.get("pickup_datetime"))
    dropoff = _parse_ts(record.get("dropoff_datetime"))
    if pickup and dropoff and dropoff < pickup:
        return False, "dropoff_after_pickup", "dropoff_datetime"

    if pickup and dropoff and record.get("trip_distance") is not None:
        duration_hours = max((dropoff - pickup).total_seconds() / 3600.0, 1 / 3600.0)
        speed_mph = float(record["trip_distance"]) / duration_hours
        max_speed = next(
            (
                rule["max_speed_mph"]
                for rule in contract.get("logical_rules", [])
                if rule.get("name") == "max_trip_speed_mph"
            ),
            100,
        )
        if speed_mph > max_speed:
            return False, "max_trip_speed_mph", "trip_distance"

    return True, None, None
