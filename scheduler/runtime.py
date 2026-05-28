"""APScheduler startup with Postgres-backed job store."""

from __future__ import annotations

from typing import TYPE_CHECKING

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from scheduler.jobs import RaceJobContext, register_all_weekend_jobs, set_race_job_context

if TYPE_CHECKING:
    from fastapi import FastAPI

_scheduler: AsyncIOScheduler | None = None


def _sync_database_url(async_url: str) -> str:
    """
    Convert async SQLAlchemy URL to sync form for APScheduler job store.

    Args:
        async_url: DATABASE_URL (postgres:// or postgresql+asyncpg://).

    Returns:
        postgresql:// URL for SQLAlchemyJobStore.
    """
    url = async_url.strip()
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    if "postgresql+asyncpg://" in url:
        return url.replace("postgresql+asyncpg://", "postgresql://", 1)
    if "postgresql+psycopg://" in url:
        return url.replace("postgresql+psycopg://", "postgresql://", 1)
    return url


def start_race_scheduler(app: FastAPI, database_url: str) -> AsyncIOScheduler | None:
    """
    Start the persistent race calendar scheduler.

    Args:
        app: FastAPI application with agent/vector_store on app.state.
        database_url: Postgres DATABASE_URL.

    Returns:
        AsyncIOScheduler instance, or None if URL missing.
    """
    global _scheduler
    if not database_url.strip():
        logger.warning("DATABASE_URL unset — race scheduler not started")
        return None

    if _scheduler is not None:
        return _scheduler

    sync_url = _sync_database_url(database_url)
    jobstores = {
        "default": SQLAlchemyJobStore(url=sync_url, tablename="apscheduler_jobs"),
    }
    _scheduler = AsyncIOScheduler(jobstores=jobstores, timezone="UTC")
    set_race_job_context(RaceJobContext(app=app))
    register_all_weekend_jobs(_scheduler)
    _scheduler.start()
    logger.info("Race calendar scheduler started (Postgres job store)")
    return _scheduler


async def stop_race_scheduler() -> None:
    """Shut down the scheduler without waiting for running jobs."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Race calendar scheduler stopped")


def get_race_scheduler() -> AsyncIOScheduler | None:
    """Return the active scheduler instance if running."""
    return _scheduler
