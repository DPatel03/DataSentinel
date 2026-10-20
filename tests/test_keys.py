"""Tests for stable Kafka ride keys."""

from __future__ import annotations

from ingestion.keys import ride_key


def test_ride_key_includes_vendor_and_locations() -> None:
    record = {
        "vendor_id": 1,
        "pickup_datetime": "2019-01-01T08:30:00",
        "pulocation_id": 161,
        "dolocation_id": 162,
    }
    assert ride_key(record) == "1|2019-01-01T08:30:00|161|162"


def test_same_pickup_different_vendor_are_distinct() -> None:
    pickup = "2019-01-01T08:30:00"
    a = {"vendor_id": 1, "pickup_datetime": pickup, "pulocation_id": 10, "dolocation_id": 20}
    b = {"vendor_id": 2, "pickup_datetime": pickup, "pulocation_id": 10, "dolocation_id": 20}
    assert ride_key(a) != ride_key(b)


def test_missing_record_uses_fallback() -> None:
    assert ride_key(None) == "unknown"
    assert ride_key({}) == "nv|np|npu|ndo"
