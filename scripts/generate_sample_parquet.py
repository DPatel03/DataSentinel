#!/usr/bin/env python3
"""Generate sample NYC taxi Parquet files for local testing (v1 + v2)."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


def _base_rows(start: datetime, count: int) -> list[dict]:
    rows = []
    for i in range(count):
        pickup = start + timedelta(minutes=i * 3)
        dropoff = pickup + timedelta(minutes=15)
        rows.append(
            {
                "VendorID": 1,
                "tpep_pickup_datetime": pickup,
                "tpep_dropoff_datetime": dropoff,
                "passenger_count": 1,
                "trip_distance": 2.5 + (i % 5),
                "RatecodeID": 1,
                "store_and_fwd_flag": "N",
                "PULocationID": 161,
                "DOLocationID": 162,
                "payment_type": 1,
                "fare_amount": 12.5,
                "extra": 0.5,
                "mta_tax": 0.5,
                "tip_amount": 2.0,
                "tolls_amount": 0.0,
                "improvement_surcharge": 0.3,
                "total_amount": 15.8,
            }
        )
    return rows


def generate_v1(path: Path, count: int = 200) -> None:
    rows = _base_rows(datetime(2019, 1, 1, 8, 0, 0), count)
    rows[10]["fare_amount"] = -14.5
    rows[20]["trip_distance"] = 150.0
    rows[30]["tpep_dropoff_datetime"] = rows[30]["tpep_pickup_datetime"] - timedelta(minutes=5)
    pq.write_table(pa.Table.from_pylist(rows), path)
    print(f"Wrote v1 sample ({len(rows)} rows, 3 dirty) -> {path}")


def generate_v2(path: Path, count: int = 200) -> None:
    rows = _base_rows(datetime(2021, 6, 1, 9, 0, 0), count)
    for row in rows:
        row["congestion_surcharge"] = 2.5
    rows[15]["fare_amount"] = -8.0
    rows[25]["trip_distance"] = 0.0
    rows[35]["passenger_count"] = 12
    pq.write_table(pa.Table.from_pylist(rows), path)
    print(f"Wrote v2 sample ({len(rows)} rows, 3 dirty) -> {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate sample taxi Parquet files")
    parser.add_argument("--output-dir", type=Path, default=Path("data"))
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    generate_v1(args.output_dir / "yellow_tripdata_2019-01_sample.parquet")
    generate_v2(args.output_dir / "yellow_tripdata_2021-06_sample.parquet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
