"""Great Expectations validation for NYC taxi ride records."""

from __future__ import annotations

from typing import Any

import pandas as pd

from validation.contract import load_contract, validate_record

__all__ = ["load_contract", "validate_record", "validate_dataframe", "build_expectation_results"]
def validate_dataframe(df: pd.DataFrame, contract: dict[str, Any] | None = None) -> pd.DataFrame:
    """Annotate dataframe with validation results."""
    contract = contract or load_contract()
    results = [validate_record(row._asdict() if hasattr(row, "_asdict") else row.to_dict(), contract) for _, row in df.iterrows()]
    df = df.copy()
    df["is_valid"] = [r[0] for r in results]
    df["rule_violated"] = [r[1] for r in results]
    df["field_name"] = [r[2] for r in results]
    return df


def build_expectation_results(df: pd.DataFrame, contract: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run batch-level Great Expectations checks using PandasDataset (GE 0.18)."""
    from great_expectations.dataset import PandasDataset

    contract = contract or load_contract()
    ge_df = PandasDataset(df)
    results: list[dict[str, Any]] = []

    for field, rules in contract["fields"].items():
        if field not in df.columns:
            continue
        if rules.get("nullable") is False:
            result = ge_df.expect_column_values_to_not_be_null(field)
            results.append(
                {
                    "expectation": "expect_column_values_to_not_be_null",
                    "column": field,
                    "success": result["success"],
                }
            )
        field_range = rules.get("range")
        if field_range:
            mostly = 1.0 - (rules.get("null_threshold_pct", 0) / 100.0)
            result = ge_df.expect_column_values_to_be_between(
                field,
                min_value=field_range[0],
                max_value=field_range[1],
                mostly=mostly,
            )
            results.append(
                {
                    "expectation": "expect_column_values_to_be_between",
                    "column": field,
                    "success": result["success"],
                }
            )

    return {
        "success": all(item["success"] for item in results),
        "results": results,
    }
