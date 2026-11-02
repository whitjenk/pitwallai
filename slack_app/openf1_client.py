"""An OpenF1 client whose responses are cached in our SQLite ``store``.

``core.api`` takes an ``OpenF1Client`` and reads it live — caching is not core's
job (see ``core/api.py``). The client accepts an optional cache object; here we
give it one backed by ``store.cache_get`` / ``store.cache_set`` so the Slack app
caches through the same SQLite file as everything else. No F1 logic lives here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from core.calendar import data_pause_at
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


class OpenF1Paused(Exception):
    """OpenF1's free data is paused for a live session and nothing is cached.

    Raised instead of making a (doomed) HTTP request during the pause, so a
    handler can tell a scheduled lockout apart from an outage. ``reopens_at`` is
    when free data returns (UTC).
    """

    def __init__(self, reopens_at: datetime) -> None:
        super().__init__(f"OpenF1 paused until {reopens_at.isoformat()}")
        self.reopens_at = reopens_at


def _now() -> datetime:
    return datetime.now(tz=UTC)


class _StoreCache:
    """Reads/writes OpenF1 responses through the SQLite ``store`` cache.

    During an OpenF1 live-session pause the live endpoints would refuse every
    request, so we lean on the cache: expired rows are served (stale beats
    nothing), and a genuine miss raises :class:`OpenF1Paused` so the client never
    makes the doomed HTTP call. Outside a pause, behaviour is unchanged.
    """

    async def get(self, key: str) -> list[dict[str, Any]] | None:
        pause = data_pause_at(_now())
        if pause is None:
            return await store.cache_get(f"openf1:{key}")
        cached = await store.cache_get(f"openf1:{key}", allow_stale=True)
        if cached is None:
            raise OpenF1Paused(pause.reopens_at)
        return cached

    async def set(
        self, key: str, endpoint: str, tier: CacheTier, data: list[dict[str, Any]]
    ) -> None:
        await store.cache_set(f"openf1:{key}", data, ttl_seconds=_TTL_SECONDS[tier])


def build_client() -> OpenF1Client:
    """Return a store-cached OpenF1 client for the handlers to pass to core."""
    return OpenF1Client(cache=_StoreCache())
