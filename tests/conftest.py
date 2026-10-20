"""Pytest bootstrap.

Import numpy before other native extensions. On macOS, importing numpy
after confluent_kafka/psycopg2 can segfault inside Accelerate/LAPACK.
"""

from __future__ import annotations

try:
    import numpy  # noqa: F401
except Exception:
    pass
