"""APScheduler job handlers for the 2026 race calendar."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from loguru import logger

from scheduler.calendar import CALENDAR_2026, RaceWeekend, get_race_weekend

if TYPE_CHECKING:
    from fastapi import FastAPI


@dataclass
class RaceJobContext:
    """Shared runtime dependencies for scheduled race jobs."""

    app: FastAPI


_ctx: RaceJobContext | None = None


def set_race_job_context(ctx: RaceJobContext) -> None:
    """Register the FastAPI app for job handlers."""
    global _ctx
    _ctx = ctx


def _require_ctx() -> RaceJobContext:
    if _ctx is None:
        raise RuntimeError("RaceJobContext not initialized — call set_race_job_context() at startup")
    return _ctx


async def job_thursday_context(race_key: str) -> None:
    """Agent 1 stub — pre-weekend context builder (Phase 6)."""
    weekend = get_race_weekend(race_key)
    logger.bind(race_key=race_key, circuit=weekend.circuit_key if weekend else None).info(
        "Agent 1 not yet implemented — thursday_context skipped"
    )


async def job_practice_analysis(race_key: str) -> None:
    """Run FP1/FP2 practice sentiment extraction (Agent 2)."""
    from circuits.profiles import get_circuit_profile
    from intelligence.practice_analyst import analyze_practice_weekend
    from openf1.client import OpenF1Client
    from scheduler.calendar import profile_circuit_key

    ctx = _require_ctx()
    app = ctx.app
    weekend = get_race_weekend(race_key)
    if weekend is None:
        logger.error("practice_analysis: unknown race_key={}", race_key)
        return

    profile_key = profile_circuit_key(weekend.circuit_key)
    circuit = get_circuit_profile(profile_key)
    if circuit is None:
        logger.error("practice_analysis: no profile for {}", profile_key)
        return

    client = OpenF1Client()
    try:
        signals = await analyze_practice_weekend(
            client=client,
            agent=app.state.agent,
            vector_store=app.state.vector_store,
            circuit=circuit,
            year=2026,
            persist=True,
        )
        logger.bind(race_key=race_key, signals=len(signals)).info("practice_analysis complete")
    except Exception as exc:
        logger.exception("practice_analysis failed race_key={}: {}", race_key, exc)
    finally:
        pass


async def job_quali_broadcast(race_key: str) -> None:
    """Generate picks and broadcast via WhatsApp."""
    from whatsapp.broadcast import broadcast_race_picks

    try:
        summary = await broadcast_race_picks(race_key)
        logger.bind(race_key=race_key, **summary).info("quali_broadcast complete")
    except Exception as exc:
        logger.exception("quali_broadcast failed race_key={}: {}", race_key, exc)


async def job_race_monitor_start(race_key: str) -> None:
    """Agent 4 stub — live race monitor (Phase 6)."""
    logger.bind(race_key=race_key).info("Agent 4 not yet implemented — race_monitor_start skipped")


async def job_post_race_scorer(race_key: str) -> None:
    """Score picks and send post-race recap."""
    from intelligence.scorer import broadcast_race_recap, score_race

    try:
        await score_race(race_key)
        recap = await broadcast_race_recap(race_key)
        logger.bind(race_key=race_key, **recap).info("post_race_scorer complete")
    except Exception as exc:
        logger.exception("post_race_scorer failed race_key={}: {}", race_key, exc)


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

    Returns:
        Number of jobs scheduled.
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
    """
    Schedule jobs for every 2026 race weekend.

    Returns:
        Total jobs scheduled across all weekends.
    """
    total = 0
    for weekend in CALENDAR_2026:
        total += register_weekend_jobs(scheduler, weekend)
    logger.bind(weekends=len(CALENDAR_2026), jobs=total).info("Race calendar jobs registered")
    return total
