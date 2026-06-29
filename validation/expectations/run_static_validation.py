#!/usr/bin/env python3
"""Run static GE validation against a Parquet file."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from ingestion.producer.mapper import parquet_row_to_avro
from validation.expectations.taxi_ride_suite import build_expectation_results, validate_dataframe


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Parquet with GE + contract rules")
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--schema-version", choices=["v1", "v2"], default=None)
    parser.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()

    if not args.file.exists():
        print(f"File not found: {args.file}", file=sys.stderr)
        return 1

    table = pq.read_table(args.file)
    rows = table.to_pylist()[: args.limit]
    records = [parquet_row_to_avro(row, schema_version=args.schema_version) for row in rows]
    df = pd.DataFrame(records)

    annotated = validate_dataframe(df)
    invalid = annotated[~annotated["is_valid"]]
    print(f"Records: {len(df)} | Valid: {annotated['is_valid'].sum()} | Invalid: {len(invalid)}")

    if len(invalid):
        print("\nSample failures:")
        print(invalid[["pickup_datetime", "rule_violated", "field_name"]].head(10).to_string(index=False))

    ge_results = build_expectation_results(df)
    print("\nGreat Expectations batch results:")
    print(json.dumps(ge_results, indent=2, default=str))

    return 0 if len(invalid) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
