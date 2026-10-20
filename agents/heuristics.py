"""Rule-based pre-classifier and repair heuristics (LLM fallback)."""

from __future__ import annotations

from agents.models import ClassificationResult, DLQPayload, FailureClass, RepairResult
from validation.contract import validate_record


def classify_heuristic(payload: DLQPayload) -> ClassificationResult:
    """Fast rule-based classification with confidence score."""
    rule = payload.rule_violated or ""
    record = payload.record or {}
    field = _field_from_rule(rule)

    if rule == "avro_deserialization_failed":
        return ClassificationResult(
            failure_class=FailureClass.SCHEMA_DRIFT,
            confidence=0.75,
            explanation="Message could not be deserialized — likely schema mismatch or corrupt payload.",
            affected_field=None,
            suggested_fix="Verify schema version and registry compatibility.",
            requires_human_review=True,
            source="heuristic",
        )

    if rule == "dropoff_after_pickup":
        return ClassificationResult(
            failure_class=FailureClass.DATA_ENTRY_ERROR,
            confidence=0.88,
            explanation="Dropoff occurs before pickup — likely swapped timestamps.",
            affected_field="dropoff_datetime",
            suggested_fix="Swap pickup and dropoff datetimes.",
            source="heuristic",
        )

    if rule == "fare_amount_range" and record.get("fare_amount") is not None:
        fare = float(record["fare_amount"])
        if fare < 0:
            return ClassificationResult(
                failure_class=FailureClass.DATA_ENTRY_ERROR,
                confidence=0.92,
                explanation=f"Negative fare ({fare}) is almost certainly a sign-entry error.",
                affected_field="fare_amount",
                suggested_fix=f"Use absolute value: {abs(fare)}",
                source="heuristic",
            )
        return ClassificationResult(
            failure_class=FailureClass.GENUINE_ANOMALY,
            confidence=0.65,
            explanation="Fare outside expected range but not obviously a sign error.",
            affected_field="fare_amount",
            requires_human_review=True,
            source="heuristic",
        )

    if rule == "trip_distance_range":
        distance = record.get("trip_distance")
        if distance is not None and float(distance) > 100:
            return ClassificationResult(
                failure_class=FailureClass.GENUINE_ANOMALY,
                confidence=0.7,
                explanation="Trip distance exceeds plausible NYC taxi range.",
                affected_field="trip_distance",
                requires_human_review=True,
                source="heuristic",
            )
        if distance is not None and float(distance) <= 0.01:
            return ClassificationResult(
                failure_class=FailureClass.KNOWN_EDGE_CASE,
                confidence=0.86,
                explanation="Zero or near-zero distance — known cancel / meter-reset pattern.",
                affected_field="trip_distance",
                suggested_fix="Do not auto-repair; exclude from distance aggregates.",
                source="heuristic",
            )
        return ClassificationResult(
            failure_class=FailureClass.DATA_ENTRY_ERROR,
            confidence=0.8,
            explanation="Trip distance out of range — likely bad entry or GPS glitch.",
            affected_field="trip_distance",
            suggested_fix="Clamp or correct distance using duration and typical speed.",
            source="heuristic",
        )

    if rule == "max_trip_speed_mph":
        return ClassificationResult(
            failure_class=FailureClass.GENUINE_ANOMALY,
            confidence=0.78,
            explanation="Implied trip speed is physically implausible.",
            affected_field="trip_distance",
            requires_human_review=True,
            source="heuristic",
        )

    if rule.endswith("_not_null"):
        return ClassificationResult(
            failure_class=FailureClass.UPSTREAM_BUG,
            confidence=0.84,
            explanation=f"Required field missing — producer omitted {field or rule}.",
            affected_field=field,
            suggested_fix="Fix the upstream producer so required fields are always emitted.",
            requires_human_review=True,
            source="heuristic",
        )

    if "schema" in rule:
        return ClassificationResult(
            failure_class=FailureClass.SCHEMA_DRIFT,
            confidence=0.72,
            explanation=f"Rule '{rule}' suggests schema mismatch or an unknown version.",
            affected_field=field,
            requires_human_review=True,
            source="heuristic",
        )

    return ClassificationResult(
        failure_class=FailureClass.UPSTREAM_BUG,
        confidence=0.55,
        explanation=f"Unclassified rule violation: {rule}",
        affected_field=field,
        requires_human_review=True,
        source="heuristic",
    )


def repair_heuristic(payload: DLQPayload, classification: ClassificationResult) -> RepairResult | None:
    """Attempt deterministic repair for data_entry_error cases."""
    if classification.failure_class != FailureClass.DATA_ENTRY_ERROR:
        return None

    record = dict(payload.record or {})
    field = classification.affected_field
    confidence = classification.confidence
    explanation = classification.explanation

    if field == "fare_amount" and record.get("fare_amount") is not None:
        original = float(record["fare_amount"])
        if original < 0:
            record["fare_amount"] = abs(original)
            explanation = f"Flipped negative fare {original} -> {record['fare_amount']}"

    elif field == "dropoff_datetime" and classification.suggested_fix and "swap" in classification.suggested_fix.lower():
        pickup = record.get("pickup_datetime")
        dropoff = record.get("dropoff_datetime")
        if pickup and dropoff:
            record["pickup_datetime"], record["dropoff_datetime"] = dropoff, pickup
            explanation = "Swapped pickup and dropoff datetimes"
            confidence = min(confidence + 0.05, 0.95)

    elif field == "trip_distance" and record.get("trip_distance") is not None:
        distance = float(record["trip_distance"])
        if distance > 100:
            record["trip_distance"] = min(distance, 50.0)
            explanation = f"Clamped excessive trip_distance {distance} -> 50.0"
            confidence = 0.6

    else:
        return None

    is_valid, rule_violated, _ = validate_record(record)
    return RepairResult(
        repaired_record=record,
        field_repaired=field,
        confidence=confidence,
        explanation=explanation,
        validation_passed=is_valid,
        routed_to_repaired=False,
    )


def _field_from_rule(rule: str) -> str | None:
    for suffix in ("_range", "_not_null", "_allowed_values"):
        if rule.endswith(suffix):
            return rule[: -len(suffix)]
    return None
