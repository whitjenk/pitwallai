"""APScheduler job handlers — delegate to Lead Strategist."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from loguru import logger

from scheduler.calendar import CALENDAR_2026, RaceWeekend, get_race_weekend

if TYPE_CHECKING:
    from fastapi import FastAPI


class RaceJobContext:
    """Shared runtime dependencies for scheduled race jobs."""

    def __init__(self, app: FastAPI) -> None:
        self.app = app


_ctx: RaceJobContext | None = None


def set_race_job_context(ctx: RaceJobContext) -> None:
    """Register the FastAPI app for job handlers."""
    global _ctx
    _ctx = ctx


def _require_ctx() -> RaceJobContext:
    if _ctx is None:
        raise RuntimeError("RaceJobContext not initialized — call set_race_job_context() at startup")
    return _ctx


def _strategist():
    from orchestrator.lead_strategist import LeadStrategist

    return LeadStrategist.from_fastapi(_require_ctx().app)


async def job_thursday_context(race_key: str) -> None:
    """Agent 1 — context builder."""
    await _strategist().run_context_builder(race_key)


async def job_practice_analysis(race_key: str) -> None:
    """Agent 2 — practice analyst."""
    await _strategist().run_practice_analyst(race_key)


async def job_quali_broadcast(race_key: str) -> None:
    """Agent 3 — quali strategist + WhatsApp broadcast."""
    await _strategist().run_quali_strategist(race_key)


async def job_race_monitor_start(race_key: str) -> None:
    """Agent 4 — live race monitor."""
    await _strategist().run_race_monitor(race_key)


async def job_post_race_scorer(race_key: str) -> None:
    """Agent 5 — scorer and learner."""
    await _strategist().run_scorer_and_learner(race_key)


def _job_times(weekend: RaceWeekend) -> list[tuple[str, datetime, Any]]:
    """Compute UTC run times for all weekend jobs."""
    return [
        ("thursday_context", weekend.race_utc - timedelta(hours=72), job_thursday_context),
        ("practice_analysis", weekend.fp2_utc + timedelta(minutes=90), job_practice_analysis),
        (
            "quali_broadcast",
            weekend.fantasy_lock_utc - timedelta(hours=3),
            job_quali_broadcast,
        ),
        ("race_monitor_start", weekend.race_utc - timedelta(minutes=5), job_race_monitor_start),
        ("post_race_scorer", weekend.race_utc + timedelta(hours=3), job_post_race_scorer),
    ]


def register_weekend_jobs(scheduler: AsyncIOScheduler, weekend: RaceWeekend) -> int:
    """
    Schedule all jobs for one race weekend.

    Skips jobs whose run time is already in the past. Uses stable job IDs
    so restarts do not duplicate work.
    """
    now = datetime.now(tz=UTC)
    scheduled = 0
    for suffix, run_at, func in _job_times(weekend):
        if run_at <= now:
            continue
        job_id = f"{weekend.race_key}:{suffix}"
        scheduler.add_job(
            func,
            trigger=DateTrigger(run_date=run_at),
            id=job_id,
            replace_existing=True,
            kwargs={"race_key": weekend.race_key},
            misfire_grace_time=3600,
        )
        scheduled += 1
        logger.debug("Scheduled job id={} at {}", job_id, run_at.isoformat())
    return scheduled


def register_all_weekend_jobs(scheduler: AsyncIOScheduler) -> int:
    """Schedule jobs for every 2026 race weekend."""
    total = 0
    for weekend in CALENDAR_2026:
        total += register_weekend_jobs(scheduler, weekend)
    logger.bind(weekends=len(CALENDAR_2026), jobs=total).info("Race calendar jobs registered")
    return total
