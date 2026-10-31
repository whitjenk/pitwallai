"""Postgres-backed TTL cache for OpenF1 API responses (legacy db layer).

This used to live in ``openf1/cache.py``, but ``openf1`` must not import the
database (brief 010). The pure key/tier helpers now live in
``openf1/cache_keys.py``; the storage table and read/write helpers stay here in
the legacy ``db`` layer, for the WhatsApp-era app that still uses Postgres. The
Slack app caches through the SQLite ``store`` instead and never touches this.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import DateTime, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column

from openf1.cache_keys import CacheTier, cache_key_for  # noqa: F401 — re-exported

from db.models import Base
from db.session import get_session

_TTL_SECONDS: dict[CacheTier, int] = {
    CacheTier.SESSION: 24 * 3600,
    CacheTier.LAP: 3600,
    CacheTier.LIVE: 30,
}


class OpenF1CacheEntry(Base):
    """Cached OpenF1 JSON response."""

    __tablename__ = "openf1_cache"

    cache_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    endpoint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tier: Mapped[str] = mapped_column(String(16), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(tz=UTC),
    )


async def cache_get(key: str) -> list[dict[str, Any]] | None:
    """
    Return cached payload if present and not expired.

    Args:
        key: Cache key.

    Returns:
        Deserialized JSON list or None.
    """
    import json

    now = datetime.now(tz=UTC)
    try:
        async with get_session() as session:
            row = await session.get(OpenF1CacheEntry, key)
            if row is None:
                return None
            # SQLite stores DateTime(timezone=True) without tzinfo, so the value
            # comes back naive — normalize to UTC before comparing with `now`.
            expires_at = row.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at <= now:
                return None
            return json.loads(row.payload_json)
    except ValueError:
        # No DATABASE_URL — treat as a cache miss so the live OpenF1 read path
        # still works (and a DB blip can't kill race monitoring).
        return None


async def cache_set(
    key: str,
    endpoint: str,
    tier: CacheTier,
    payload: list[dict[str, Any]],
) -> None:
    """
    Store API response with TTL.

    Args:
        key: Cache key.
        endpoint: Endpoint name.
        tier: TTL tier.
        payload: Raw JSON list to store.
    """
    import json

    expires = datetime.now(tz=UTC) + timedelta(seconds=_TTL_SECONDS[tier])
    try:
        async with get_session() as session:
            row = await session.get(OpenF1CacheEntry, key)
            if row is None:
                row = OpenF1CacheEntry(
                    cache_key=key,
                    endpoint=endpoint,
                    tier=tier.value,
                    payload_json=json.dumps(payload, default=str),
                    expires_at=expires,
                )
                session.add(row)
            else:
                row.payload_json = json.dumps(payload, default=str)
                row.expires_at = expires
                row.tier = tier.value
    except ValueError:
        # No DATABASE_URL — skip caching; the API result is still returned.
        return


async def purge_expired_cache() -> int:
    """
    Delete expired cache rows.

    Returns:
        Number of rows removed.
    """
    now = datetime.now(tz=UTC)
    async with get_session() as session:
        result = await session.execute(
            select(OpenF1CacheEntry).where(OpenF1CacheEntry.expires_at <= now)
        )
        rows = list(result.scalars().all())
        for row in rows:
            await session.delete(row)
        return len(rows)
