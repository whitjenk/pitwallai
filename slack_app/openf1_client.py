"""An OpenF1 client whose responses are cached in our SQLite ``store``.

``core.api`` takes an ``OpenF1Client`` and reads it live — caching is not core's
job (see ``core/api.py``). The base client has its own Postgres cache from the
WhatsApp era; that layer degrades to a no-op without ``DATABASE_URL``, so the
Slack app wraps the client and caches through ``store.cache_get`` /
``store.cache_set`` instead, as the brief asks. No F1 logic lives here.
"""

from __future__ import annotations

from typing import Any

from openf1.cache import CacheTier, cache_key_for
from openf1.client import OpenF1Client

import store

# TTLs mirror the base client's tiers: sessions change rarely, laps hourly,
# live timing every few seconds.
_TTL_SECONDS: dict[CacheTier, int] = {
    CacheTier.SESSION: 24 * 3600,
    CacheTier.LAP: 3600,
    CacheTier.LIVE: 30,
}


class StoreCachedOpenF1Client(OpenF1Client):
    """``OpenF1Client`` that reads/writes the SQLite ``store`` cache first."""

    async def _fetch_raw(
        self, endpoint: str, params: dict[str, Any], *, tier: CacheTier
    ) -> list[dict[str, Any]]:
        key = f"openf1:{cache_key_for(endpoint, params)}"
        cached = await store.cache_get(key)
        if cached is not None:
            return cached  # type: ignore[return-value]
        data = await super()._fetch_raw(endpoint, params, tier=tier)
        await store.cache_set(key, data, ttl_seconds=_TTL_SECONDS[tier])
        return data


def build_client() -> StoreCachedOpenF1Client:
    """Return a store-cached OpenF1 client for the handlers to pass to core."""
    return StoreCachedOpenF1Client()
