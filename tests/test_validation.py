"""Tests for YAML data-contract validation (no Kafka required)."""

from __future__ import annotations

from validation.contract import load_contract, validate_record


def _valid_v1() -> dict:
    return {
        "pickup_datetime": "2019-01-01T08:30:00",
        "dropoff_datetime": "2019-01-01T08:45:00",
        "fare_amount": 14.5,
        "trip_distance": 2.5,
        "total_amount": 16.0,
        "passenger_count": 1,
        "schema_version": "v1",
    }


def test_load_contract_has_required_sections() -> None:
    contract = load_contract()
    assert contract["contract_version"] == "1.0.0"
    assert "fields" in contract
    assert "logical_rules" in contract
    assert "fare_amount" in contract["fields"]


def test_valid_record_passes() -> None:
    is_valid, rule, field = validate_record(_valid_v1())
    assert is_valid
    assert rule is None
    assert field is None


def test_negative_fare_fails_range() -> None:
    record = {**_valid_v1(), "fare_amount": -14.5}
    is_valid, rule, field = validate_record(record)
    assert not is_valid
    assert rule == "fare_amount_range"
    assert field == "fare_amount"


def test_swapped_datetimes_fail_logical_rule() -> None:
    record = {
        **_valid_v1(),
        "pickup_datetime": "2019-01-01T09:00:00",
        "dropoff_datetime": "2019-01-01T08:30:00",
    }
    is_valid, rule, field = validate_record(record)
    assert not is_valid
    assert rule == "dropoff_after_pickup"
    assert field == "dropoff_datetime"


def test_missing_pickup_fails_not_null() -> None:
    record = _valid_v1()
    del record["pickup_datetime"]
    is_valid, rule, field = validate_record(record)
    assert not is_valid
    assert rule == "pickup_datetime_not_null"
    assert field == "pickup_datetime"


def test_implausible_speed_fails() -> None:
    record = {
        **_valid_v1(),
        "pickup_datetime": "2019-01-01T08:00:00",
        "dropoff_datetime": "2019-01-01T08:01:00",
        "trip_distance": 80.0,
    }
    is_valid, rule, field = validate_record(record)
    assert not is_valid
    assert rule == "max_trip_speed_mph"


def test_v2_congestion_surcharge_out_of_range() -> None:
    record = {
        **_valid_v1(),
        "schema_version": "v2",
        "congestion_surcharge": 99.0,
    }
    is_valid, rule, field = validate_record(record)
    assert not is_valid
    assert rule == "congestion_surcharge_range"
    assert field == "congestion_surcharge"


def test_v1_ignores_v2_only_fields() -> None:
    record = {**_valid_v1(), "congestion_surcharge": 99.0}
    is_valid, rule, _ = validate_record(record)
    assert is_valid
    assert rule is None
