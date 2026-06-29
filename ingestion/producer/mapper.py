"""Map NYC TLC Parquet rows to Avro records."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def _to_iso(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _row_get(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in row and row[name] is not None:
            return row[name]
    return None


def infer_schema_version(row: dict[str, Any], explicit: str | None = None) -> str:
    if explicit:
        return explicit

    pickup = _row_get(row, "tpep_pickup_datetime", "pickup_datetime")
    if pickup is not None:
        year = pickup.year if hasattr(pickup, "year") else int(str(pickup)[:4])
        return "v1" if year < 2020 else "v2"

    if "congestion_surcharge" in row or "Congestion_surcharge" in row:
        return "v2"
    return "v1"


def parquet_row_to_avro(row: dict[str, Any], schema_version: str | None = None) -> dict[str, Any]:
    version = infer_schema_version(row, schema_version)

    record: dict[str, Any] = {
        "vendor_id": _to_int(_row_get(row, "VendorID", "vendor_id")),
        "pickup_datetime": _to_iso(_row_get(row, "tpep_pickup_datetime", "pickup_datetime")),
        "dropoff_datetime": _to_iso(_row_get(row, "tpep_dropoff_datetime", "dropoff_datetime")),
        "passenger_count": _to_float(_row_get(row, "passenger_count", "Passenger_count")),
        "trip_distance": _to_float(_row_get(row, "trip_distance", "Trip_distance")),
        "ratecode_id": _to_float(_row_get(row, "RatecodeID", "ratecode_id")),
        "store_and_fwd_flag": _row_get(row, "store_and_fwd_flag", "Store_and_fwd_flag"),
        "pulocation_id": _to_int(_row_get(row, "PULocationID", "pulocation_id")),
        "dolocation_id": _to_int(_row_get(row, "DOLocationID", "dolocation_id")),
        "payment_type": _to_int(_row_get(row, "payment_type", "Payment_type")),
        "fare_amount": _to_float(_row_get(row, "fare_amount", "Fare_amount")),
        "extra": _to_float(_row_get(row, "extra", "Extra")),
        "mta_tax": _to_float(_row_get(row, "mta_tax", "MTA_tax")),
        "tip_amount": _to_float(_row_get(row, "tip_amount", "Tip_amount")),
        "tolls_amount": _to_float(_row_get(row, "tolls_amount", "Tolls_amount")),
        "improvement_surcharge": _to_float(
            _row_get(row, "improvement_surcharge", "Improvement_surcharge")
        ),
        "total_amount": _to_float(_row_get(row, "total_amount", "Total_amount")),
        "schema_version": version,
    }

    if version == "v2":
        record["congestion_surcharge"] = _to_float(
            _row_get(row, "congestion_surcharge", "Congestion_surcharge")
        )

    return record
