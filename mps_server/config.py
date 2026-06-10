"""Small, fail-closed configuration helpers shared by server modules."""

from __future__ import annotations

import os
from pathlib import Path


def read_secret(name: str, default: str | None = None) -> str | None:
    """Read NAME or NAME_FILE, rejecting ambiguous and unsafe secret files."""
    value = os.getenv(name)
    file_name = os.getenv(f"{name}_FILE")
    if value and file_name:
        raise RuntimeError(f"Set only one of {name} or {name}_FILE")
    if file_name:
        path = Path(file_name)
        if not path.is_file():
            raise RuntimeError(f"{name}_FILE does not reference a regular file")
        if path.stat().st_size > 16_384:
            raise RuntimeError(f"{name}_FILE is unexpectedly large")
        value = path.read_text(encoding="utf-8").strip()
    return value if value is not None else default
