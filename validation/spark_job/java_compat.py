"""Java version helpers for PySpark."""

from __future__ import annotations

import os
import re
import subprocess
import sys


def _java_major_version() -> int | None:
    try:
        result = subprocess.run(["java", "-version"], capture_output=True, text=True)
        output = result.stderr or result.stdout
        match = re.search(r'version "(\d+)', output)
        if not match:
            return None
        major = int(match.group(1))
        return major if major != 1 else int(output.split(".")[1])
    except OSError:
        return None


def ensure_spark_java() -> None:
    """Point JAVA_HOME at Java 17 when the default JDK is too new for PySpark 3.5."""
    if os.environ.get("JAVA_HOME"):
        return

    major = _java_major_version()
    if major is not None and major <= 21:
        return

    try:
        result = subprocess.run(
            ["/usr/libexec/java_home", "-v", "17"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        print(
            "PySpark requires Java 17 or 21. Your default Java is too new.\n"
            "Install Java 17, or run the Python validator instead:\n"
            "  python -m validation.streaming_validator",
            file=sys.stderr,
        )
        sys.exit(1)

    java_home = result.stdout.strip()
    os.environ["JAVA_HOME"] = java_home
    os.environ["PATH"] = f"{java_home}/bin:{os.environ.get('PATH', '')}"
    print(f"Using JAVA_HOME={java_home} for PySpark")
