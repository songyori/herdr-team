"""ID 와 시각."""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

PREFIXES = ("run", "task", "dsp")


def new_id(prefix: str) -> str:
    if prefix not in PREFIXES:
        raise ValueError(f"모르는 ID 접두사: {prefix}")
    return f"{prefix}-{secrets.token_hex(4)}"


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
