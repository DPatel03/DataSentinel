"""Shared config helpers — loads .env and builds connection strings."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"


def load_env() -> None:
    """Load .env into os.environ if present."""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def timescaledb_dsn() -> str:
    load_env()
    return os.getenv(
        "TIMESCALEDB_DSN",
        "postgresql://datasentinel:datasentinel@127.0.0.1:5433/datasentinel",
    )
