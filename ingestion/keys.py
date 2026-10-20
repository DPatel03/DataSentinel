"""Stable Kafka keys for taxi ride records."""

from __future__ import annotations

from typing import Any


def ride_key(record: dict[str, Any] | None, fallback: str = "unknown") -> str:
    """Vendor + pickup + locations — unique enough to avoid pickup-time collisions."""
    if record is None:
        return fallback
    return "|".join(
        (
            str(record.get("vendor_id") if record.get("vendor_id") is not None else "nv"),
            str(record.get("pickup_datetime") or "np"),
            str(record.get("pulocation_id") if record.get("pulocation_id") is not None else "npu"),
            str(record.get("dolocation_id") if record.get("dolocation_id") is not None else "ndo"),
        )
    )
