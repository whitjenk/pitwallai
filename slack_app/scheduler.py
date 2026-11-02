"""A tiny in-process job runner for the Slack app (brief 012).

No APScheduler and no Slack ``chat.scheduleMessage`` — just one asyncio loop in
the Bolt process, the same pattern as the price-refresh loop in ``app.py``. A
job is due in the window ``[due_at, due_at + grace]``; it runs at most once, and
"already ran" is persisted in the store's ``job_runs`` table so a restart never
re-runs a finished job. A job that raises isn't marked done — it's retried on the
next tick while still inside its grace window.

The only jobs shipped today warm the OpenF1 cache each time a live-session
lockout lifts, so the next lockout already has fresh-enough data to serve. Later
briefs register channel/DM posts here (ROADMAP → Social layer).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from loguru import logger

import store
from core import calendar as cal
from core.api import project_race, score_lineup
from core.calendar import RaceWeekend, get_next_race_weekend
from core.types import Lineup
from slack_app.openf1_client import build_client

# How often the loop wakes up to check for due jobs.
TICK_SECONDS = 60
# Warm-up jobs fire a little after a window reopens; OpenF1 sometimes lags, so a
# second, later attempt catches data that wasn't published at the first.
WARMUP_OFFSETS_MIN = (5, 40)
_DEFAULT_GRACE = timedelta(hours=6)


@dataclass(frozen=True)
class Job:
    """A unit of work due at ``due_at``, runnable until ``due_at + grace``."""

    key: str
    due_at: datetime
    run: Callable[[], Awaitable[None]]
    grace: timedelta = field(default=_DEFAULT_GRACE)


def scheduler_enabled() -> bool:
    """False when ``PITWALL_SCHEDULER=off`` (local runs alongside Railway, CLI)."""
    return os.getenv("PITWALL_SCHEDULER", "").strip().lower() != "off"


def _warm_up(weekend: RaceWeekend, *, is_race: bool) -> Callable[[], Awaitable[None]]:
    """A job body that re-fetches, through the cache, what the handlers read."""

    async def run() -> None:
        client = build_client()
        if is_race:
            # Warms what `score` reads: race classification + driver roster.
            await score_lineup(Lineup(drivers=[], constructors=[]), weekend.race_key, client)
        else:
            # Warms what `picks`/`grade`/`lock` read: practice session keys + laps.
            await project_race(weekend.race_key, client)

    return run


def build_warmup_jobs(weekend: RaceWeekend) -> list[Job]:
    """Two cache-warm jobs per session, just after each lockout window reopens."""
    jobs: list[Job] = []
    for session in cal.sessions(weekend):
        reopens = session.end + cal.DATA_PAUSE_MARGIN
        run = _warm_up(weekend, is_race=session.name == "Race")
        for offset in WARMUP_OFFSETS_MIN:
            jobs.append(
                Job(
                    key=f"warmup:{weekend.race_key}:{session.name}:{offset}",
                    due_at=reopens + timedelta(minutes=offset),
                    run=run,
                )
            )
    return jobs


def default_jobs() -> list[Job]:
    """Warm-up jobs for the next race weekend, or none if the season's over."""
    weekend = get_next_race_weekend()
    return build_warmup_jobs(weekend) if weekend is not None else []


async def run_due_jobs(jobs: list[Job], now: datetime) -> None:
    """Run each job due at ``now`` that hasn't already finished.

    A job is due in ``[due_at, due_at + grace]``. Success is recorded so it never
    re-runs; a failure is logged and left unrecorded, so the next tick retries it
    while still inside the grace window.
    """
    for job in jobs:
        if not (job.due_at <= now <= job.due_at + job.grace):
            continue
        if await store.job_has_run(job.key):
            continue
        try:
            await job.run()
        except Exception as exc:  # retried next tick while still within grace
            logger.warning("scheduler job {} failed (will retry): {}", job.key, exc)
            continue
        await store.mark_job_run(job.key)
        logger.info("scheduler job {} done", job.key)


async def scheduler_loop(
    build_jobs: Callable[[], list[Job]] = default_jobs,
    *,
    interval_seconds: int = TICK_SECONDS,
) -> None:
    """Check for due jobs every ``interval_seconds`` forever (best-effort)."""
    while True:
        try:
            await run_due_jobs(build_jobs(), datetime.now(tz=UTC))
        except Exception as exc:  # a bad tick must never kill the loop
            logger.warning("scheduler tick failed: {}", exc)
        await asyncio.sleep(interval_seconds)


def start_scheduler(
    build_jobs: Callable[[], list[Job]] = default_jobs,
) -> asyncio.Task | None:
    """Start the loop as a background task, or return ``None`` when disabled."""
    if not scheduler_enabled():
        logger.info("scheduler disabled (PITWALL_SCHEDULER=off)")
        return None
    logger.info("scheduler starting (tick {}s)", TICK_SECONDS)
    return asyncio.create_task(scheduler_loop(build_jobs))
