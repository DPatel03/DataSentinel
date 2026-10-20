"""Write contract breach events to TimescaleDB."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import psycopg2
from psycopg2.extras import execute_values


class BreachWriter:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self._conn = None

    def connect(self) -> None:
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self.dsn)

    def close(self) -> None:
        if self._conn and not self._conn.closed:
            self._conn.close()

    def write_breaches(self, breaches: list[dict[str, Any]]) -> None:
        if not breaches:
            return

        self.connect()
        rows = [
            (
                breach.get("time", datetime.now(timezone.utc)),
                breach["rule_name"],
                breach.get("field_name"),
                breach["contract_version"],
                breach.get("failure_count", 1),
                json.dumps(breach.get("sample_record"), default=str),
                breach.get("record_key"),
            )
            for breach in breaches
        ]

        with self._conn.cursor() as cursor:
            execute_values(
                cursor,
                """
                INSERT INTO contract_breaches
                    (time, rule_name, field_name, contract_version, failure_count, sample_record, record_key)
                VALUES %s
                """,
                rows,
            )
        self._conn.commit()

    def write_validation_events(self, events: list[dict[str, Any]]) -> None:
        if not events:
            return
        self.connect()
        rows = [
            (
                event.get("time", datetime.now(timezone.utc)),
                event["is_valid"],
                event.get("latency_ms"),
                event.get("rule_name"),
                event.get("record_key"),
            )
            for event in events
        ]
        with self._conn.cursor() as cursor:
            execute_values(
                cursor,
                """
                INSERT INTO validation_events
                    (time, is_valid, latency_ms, rule_name, record_key)
                VALUES %s
                """,
                rows,
            )
        self._conn.commit()
