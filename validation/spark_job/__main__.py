#!/usr/bin/env python3
"""Start the PySpark streaming validation job."""

from __future__ import annotations

import argparse
import os

from pyspark.sql import SparkSession

from validation.config import load_env, timescaledb_dsn
from validation.spark_job.java_compat import ensure_spark_java
from validation.spark_job.validator import SparkStreamingValidator


def main() -> int:
    ensure_spark_java()
    load_env()

    parser = argparse.ArgumentParser(description="PySpark Kafka validator")
    parser.add_argument("--bootstrap-servers", default=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"))
    parser.add_argument("--registry-url", default=os.getenv("SCHEMA_REGISTRY_URL", "http://localhost:8081"))
    parser.add_argument("--db-dsn", default=timescaledb_dsn())
    parser.add_argument("--checkpoint-dir", default="/tmp/datasentinel-checkpoints")
    args = parser.parse_args()

    spark = (
        SparkSession.builder.appName("DataSentinelValidator")
        .master("local[*]")
        .config(
            "spark.jars.packages",
            "org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.1",
        )
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")

    validator = SparkStreamingValidator(
        spark=spark,
        bootstrap_servers=args.bootstrap_servers,
        registry_url=args.registry_url,
        db_dsn=args.db_dsn,
        checkpoint_dir=args.checkpoint_dir,
    )
    validator.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
