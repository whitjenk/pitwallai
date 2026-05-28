"""Background scheduler for periodic picks generation."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from loguru import logger

from intelligence.picks_config import PicksSettings
from intelligence.picks_pipeline import PicksRunResult, run_picks_pipeline
from openf1.client import OpenF1Client

if TYPE_CHECKING:
    from fastapi import FastAPI


class PicksScheduler:
    """
    Periodically runs the picks pipeline during an active race weekend.

    Uses a lock so overlapping runs never hammer OpenF1 concurrently.
    """

    def __init__(self, app: FastAPI, settings: PicksSettings) -> None:
        """
        Initialize the scheduler.

        Args:
            app: FastAPI application (agent, vector_store, settings on app.state).
            settings: Picks interval and override configuration.
        """
        self._app = app
        self._settings = settings
        self._task: asyncio.Task[Any] | None = None
        self._lock = asyncio.Lock()
        self._running = False

    def start(self) -> None:
        """Start the background picks loop."""
        if self._task is not None:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="picks_scheduler")
        logger.bind(interval_s=self._settings.interval_seconds).info(
            "Picks scheduler started"
        )

    async def stop(self) -> None:
        """Cancel the background loop."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Picks scheduler stopped")

    async def run_once(
        self,
        *,
        phone: str | None = None,
        circuit_key: str | None = None,
        year: int | None = None,
        persist_picks: bool = True,
    ) -> PicksRunResult | None:
        """
        Execute one picks pipeline run.

        Args:
            phone: Optional subscriber phone for personalized picks.
            circuit_key: Optional circuit override.
            year: Optional championship year.
            persist_picks: Write to picks audit log.

        Returns:
            PicksRunResult or None if the run was skipped (lock held / disabled).
        """
        if self._lock.locked():
            logger.warning("Picks pipeline already running — skipping")
            return None
        async with self._lock:
            return await self._execute(
                phone=phone,
                circuit_key=circuit_key,
                year=year,
                persist_picks=persist_picks,
            )

    async def _execute(
        self,
        *,
        phone: str | None,
        circuit_key: str | None,
        year: int | None,
        persist_picks: bool,
    ) -> PicksRunResult:
        client = OpenF1Client()
        try:
            result = await run_picks_pipeline(
                client=client,
                agent=self._app.state.agent,
                vector_store=self._app.state.vector_store,
                settings=self._app.state.settings,
                ctx=self._app.state.orchestrator_context,
                year=year or self._settings.race_year,
                circuit_key=circuit_key or self._settings.circuit_key_override,
                phone=phone,
                persist_picks=persist_picks,
            )
            self._app.state.last_picks_result = result
            logger.bind(
                circuit=result.weekend.circuit_key,
                picks=len(result.output.picks),
                personalized=result.output.personalized,
            ).info("Picks pipeline completed")
            return result

    async def _loop(self) -> None:
        """Background loop — initial run then sleep interval."""
        await asyncio.sleep(5)
        while self._running:
            try:
                await self._execute(
                    phone=None,
                    circuit_key=self._settings.circuit_key_override,
                    year=self._settings.race_year,
                    persist_picks=True,
                )
            except Exception as exc:
                logger.exception("Scheduled picks run failed: {}", exc)
            await asyncio.sleep(self._settings.interval_seconds)
