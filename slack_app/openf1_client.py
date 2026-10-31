"""An OpenF1 client whose responses are cached in our SQLite ``store``.

``core.api`` takes an ``OpenF1Client`` and reads it live — caching is not core's
job (see ``core/api.py``). The client accepts an optional cache object; here we
give it one backed by ``store.cache_get`` / ``store.cache_set`` so the Slack app
caches through the same SQLite file as everything else. No F1 logic lives here.
"""

from __future__ import annotations

from typing import Any

from openf1.cache_keys import CacheTier
from openf1.client import OpenF1Client

import store

# TTLs mirror the endpoint tiers: sessions change rarely, laps hourly, live
# timing every few seconds.
_TTL_SECONDS: dict[CacheTier, int] = {
    CacheTier.SESSION: 24 * 3600,
    CacheTier.LAP: 3600,
    CacheTier.LIVE: 30,
}


class _StoreCache:
    """Reads/writes OpenF1 responses through the SQLite ``store`` cache."""

    async def get(self, key: str) -> list[dict[str, Any]] | None:
        return await store.cache_get(f"openf1:{key}")

    async def set(
        self, key: str, endpoint: str, tier: CacheTier, data: list[dict[str, Any]]
    ) -> None:
        await store.cache_set(f"openf1:{key}", data, ttl_seconds=_TTL_SECONDS[tier])


def build_client() -> OpenF1Client:
    """Return a store-cached OpenF1 client for the handlers to pass to core."""
    return OpenF1Client(cache=_StoreCache())
