"""Rolling buffer of recently validated records for DLQ context."""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


def _parse_ts(value: str) -> datetime:
    if not value:
        return datetime.min
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass
class GoodRecordBuffer:
    max_size: int = 1000
    _records: list[dict[str, Any]] = field(default_factory=list)
    _pickup_times: list[datetime] = field(default_factory=list)

    def add(self, record: dict[str, Any]) -> None:
        pickup = _parse_ts(record.get("pickup_datetime", ""))
        idx = bisect.bisect_left(self._pickup_times, pickup)
        self._pickup_times.insert(idx, pickup)
        self._records.insert(idx, record)

        overflow = len(self._records) - self.max_size
        if overflow > 0:
            self._records = self._records[overflow:]
            self._pickup_times = self._pickup_times[overflow:]

    def nearest(self, failed_record: dict[str, Any], count: int = 5) -> list[dict[str, Any]]:
        if not self._records:
            return []

        target = _parse_ts(failed_record.get("pickup_datetime", ""))
        idx = bisect.bisect_left(self._pickup_times, target)

        candidates: list[tuple[float, dict[str, Any]]] = []
        for offset in range(max(idx - count, 0), min(idx + count, len(self._records))):
            delta = abs((self._pickup_times[offset] - target).total_seconds())
            candidates.append((delta, self._records[offset]))

        candidates.sort(key=lambda item: item[0])
        return [record for _, record in candidates[:count]]
