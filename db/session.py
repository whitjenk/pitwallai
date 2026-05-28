"""Async SQLAlchemy engine and session factory."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from loguru import logger
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from db.models import Base
from whatsapp.settings import get_whatsapp_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _normalize_database_url(url: str) -> str:
    """
    Convert Railway/Heroku postgres URLs to async SQLAlchemy driver form.

    Args:
        url: Raw DATABASE_URL from the environment.

    Returns:
        URL suitable for create_async_engine (postgresql+asyncpg).
    """
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def get_engine() -> AsyncEngine:
    """
    Return the shared async engine, creating it on first use.

    Returns:
        AsyncEngine instance.

    Raises:
        ValueError: If DATABASE_URL is not set.
    """
    global _engine, _session_factory
    if _engine is not None:
        return _engine

    raw_url = get_whatsapp_settings().database_url.strip()
    if not raw_url:
        raise ValueError("DATABASE_URL is not configured")

    _engine = create_async_engine(
        _normalize_database_url(raw_url),
        echo=False,
        pool_pre_ping=True,
    )
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """
    Return the async session factory.

    Returns:
        Configured async_sessionmaker.
    """
    get_engine()
    assert _session_factory is not None
    return _session_factory


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Yield an async database session with automatic commit/rollback.

    Yields:
        AsyncSession bound to the shared engine.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """
    Create database tables if they do not exist.

    Skips quietly when DATABASE_URL is unset (e.g. local dashboard-only runs).
    """
    settings = get_whatsapp_settings()
    if not settings.database_url.strip():
        logger.warning("DATABASE_URL unset — subscriber tables not initialized")
        return

    from db.migrate import upgrade_schema

    engine = get_engine()
    await upgrade_schema(engine)
