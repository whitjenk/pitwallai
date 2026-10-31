"""Pure cache helpers for OpenF1 responses — TTL tiers and key hashing.

No storage backend lives here, so this module is safe for ``openf1.client`` and
any cache implementation to import without dragging in a database.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any


class CacheTier(str, Enum):
    """TTL policy buckets for OpenF1 endpoints."""

    SESSION = "session"  # 24 hours
    LAP = "lap"  # 1 hour
    LIVE = "live"  # 30 seconds


def cache_key_for(endpoint: str, params: dict[str, Any]) -> str:
    """
    Build a stable cache key from endpoint and query parameters.

    Args:
        endpoint: API path segment (e.g. laps).
        params: Query parameters.

    Returns:
        SHA256 hex digest (truncated).
    """
    normalized = json.dumps({"endpoint": endpoint, "params": params}, sort_keys=True, default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:64]
