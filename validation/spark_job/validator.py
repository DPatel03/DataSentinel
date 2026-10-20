"""PySpark streaming validator — Kafka raw -> validated / dead-letter."""

from __future__ import annotations

from pyspark.sql import DataFrame, SparkSession

from validation.record_processor import RecordProcessor


class SparkStreamingValidator:
    def __init__(
        self,
        spark: SparkSession,
        bootstrap_servers: str,
        registry_url: str,
        db_dsn: str,
        contract_version: str = "1.0.0",
        checkpoint_dir: str = "/tmp/datasentinel-checkpoints",
    ) -> None:
        self.spark = spark
        self.bootstrap_servers = bootstrap_servers
        self.checkpoint_dir = checkpoint_dir
        self.processor = RecordProcessor(
            bootstrap_servers=bootstrap_servers,
            registry_url=registry_url,
            db_dsn=db_dsn,
            contract_version=contract_version,
        )

    def process_batch(self, batch_df: DataFrame, batch_id: int) -> None:
        rows = batch_df.collect()
        if not rows:
            return

        for row in rows:
            self.processor.process_message(row.value)

        breaches = self.processor.flush()
        print(f"Batch {batch_id}: processed {len(rows)} messages, {breaches} breaches")

    def run(self) -> None:
        raw_stream = (
            self.spark.readStream.format("kafka")
            .option("kafka.bootstrap.servers", self.bootstrap_servers)
            .option("subscribe", "taxi.rides.raw")
            .option("startingOffsets", "earliest")
            .option("failOnDataLoss", "false")
            .load()
            .selectExpr("CAST(key AS STRING) as key", "value")
        )

        query = (
            raw_stream.writeStream.foreachBatch(self.process_batch)
            .option("checkpointLocation", self.checkpoint_dir)
            .trigger(processingTime="5 seconds")
            .start()
        )

        try:
            query.awaitTermination()
        finally:
            self.processor.close()
