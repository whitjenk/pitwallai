"""Idempotent schema upgrades for existing Postgres deployments."""

from __future__ import annotations

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from db.models import Base

# create_all() creates new tables; these ALTERs add Phase 7+ columns on existing DBs.
_COLUMN_MIGRATIONS: tuple[str, ...] = (
    "ALTER TABLE picks ADD COLUMN IF NOT EXISTS pick_status VARCHAR(16) NOT NULL DEFAULT 'sent'",
    "ALTER TABLE subscribers ADD COLUMN IF NOT EXISTS rehearsal_complete BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE subscribers ADD COLUMN IF NOT EXISTS share_cards_private BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE subscribers ADD COLUMN IF NOT EXISTS races_received INTEGER NOT NULL DEFAULT 0",
    # Two-phase webhook claim — status + claimed_at on the dedup ledger.
    "ALTER TABLE processed_inbound_messages ADD COLUMN IF NOT EXISTS status VARCHAR(16) NOT NULL DEFAULT 'done'",
    "ALTER TABLE processed_inbound_messages ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
    # Decode-time provenance for the "called it" recap.
    "ALTER TABLE race_events ADD COLUMN IF NOT EXISTS decoded_at_utc TIMESTAMPTZ",
)


async def upgrade_schema(engine: AsyncEngine) -> None:
    """
    Ensure all ORM tables and schema revisions exist.

    Order: Alembic revisions (authoritative for renames/drops) → create_all
    (catches new models before a migration is written) → legacy additive ALTERs.
    """
    import asyncio

    import openf1.cache  # noqa: F401 — OpenF1CacheEntry on Base.metadata

    from db.alembic_runner import run_alembic_upgrade

    await asyncio.to_thread(run_alembic_upgrade)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for stmt in _COLUMN_MIGRATIONS:
            await conn.execute(text(stmt))
    logger.info("Database schema upgrade complete (Alembic + create_all + legacy ALTERs)")
