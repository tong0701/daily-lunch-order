"""Load project .env into os.environ (no external dependency)."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_project_env(path: Path | None = None) -> None:
    """Set env vars from .env if not already defined in the shell."""
    env_path = path or ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        # Overwrite empty shell placeholders (e.g. after sourcing .env before fill-in).
        if key not in os.environ or not os.environ.get(key):
            os.environ[key] = value
