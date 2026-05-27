"""Rehearsal engine for scripted race radio replay."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from loguru import logger

from pitwallai.agents.radio_intercept.enums import StreamEventType, UrgencyLevel
from pitwallai.agents.radio_intercept.models import (
    DecodedTransmission,
    RehearsalScenario,
    WebSocketEvent,
)
from pitwallai.agents.radio_intercept.seed_data import MONACO_REHEARSAL_SCENARIO

if TYPE_CHECKING:
    from pitwallai.agents.radio_intercept.stream_handler import RadioInterceptDecoder

SCENARIOS: dict[str, RehearsalScenario] = {
    "monaco_2024": MONACO_REHEARSAL_SCENARIO,
}


class RehearsalEngine:
    """
    Replays scripted radio events into the decoder input queue at a configurable rate.

    Tracks progress and emits a summary WebSocket event when the scenario completes.
    """

    def __init__(self, decoder: RadioInterceptDecoder, scenario: RehearsalScenario) -> None:
        """
        Initialize the rehearsal engine.

        Args:
            decoder: Active RadioInterceptDecoder pipeline.
            scenario: Scripted scenario to replay.
        """
        self._decoder = decoder
        self._scenario = scenario
        self._cancelled = False
        self._task: asyncio.Task[None] | None = None
        self._current_event = 0
        self._current_lap = 0
        self._started_at: float | None = None
        self._decoded_transmissions: list[DecodedTransmission] = []
        self._log = logger.bind(scenario=scenario.name)

    @property
    def scenario(self) -> RehearsalScenario:
        """Return the active rehearsal scenario."""
        return self._scenario

    @staticmethod
    def estimate_duration_seconds(
        scenario: RehearsalScenario,
        speed_multiplier: float = 3.0,
    ) -> float:
        """
        Estimate total replay duration at a given speed multiplier.

        Args:
            scenario: Scenario containing ordered events.
            speed_multiplier: Playback speed multiplier.

        Returns:
            Estimated duration in seconds.
        """
        if not scenario.events:
            return 0.0
        total_gap = 0.0
        for index in range(1, len(scenario.events)):
            prev_ts = scenario.events[index - 1].timestamp
            curr_ts = scenario.events[index].timestamp
            gap = (curr_ts - prev_ts).total_seconds()
            total_gap += gap if gap > 0 else 5.0
        return total_gap / max(speed_multiplier, 0.1)

    async def run(self, speed_multiplier: float = 3.0) -> None:
        """
        Replay scenario events into the decoder input queue.

        Args:
            speed_multiplier: Playback speed (higher = faster).

        Raises:
            asyncio.CancelledError: When stop() cancels the active run.
        """
        self._cancelled = False
        self._current_event = 0
        self._decoded_transmissions = []
        self._started_at = time.perf_counter()
        events = self._scenario.events
        self._log.bind(events=len(events), speed=speed_multiplier).info(
            "Rehearsal started"
        )

        collector: asyncio.Queue[WebSocketEvent] = asyncio.Queue(maxsize=200)
        self._decoder.subscribe(collector)

        async def _collect_decoded() -> None:
            while not self._cancelled:
                try:
                    event = await asyncio.wait_for(collector.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                if event.event_type != StreamEventType.TRANSMISSION_DECODED:
                    continue
                if isinstance(event.payload, DecodedTransmission):
                    self._decoded_transmissions.append(event.payload)
                    if event.payload.lap_number is not None:
                        self._current_lap = event.payload.lap_number

        collector_task = asyncio.create_task(_collect_decoded())

        try:
            for index, event in enumerate(events):
                if self._cancelled:
                    break

                self._current_event = index + 1
                if event.lap_number is not None:
                    self._current_lap = event.lap_number

                self._decoder._deps.session_key = event.session_key
                await self._decoder._input_queue.put(event)

                if index < len(events) - 1:
                    prev_ts = event.timestamp
                    next_ts = events[index + 1].timestamp
                    gap_seconds = (next_ts - prev_ts).total_seconds()
                    if gap_seconds <= 0:
                        gap_seconds = 5.0
                    await asyncio.sleep(gap_seconds / max(speed_multiplier, 0.1))

            await asyncio.sleep(2.0 / max(speed_multiplier, 0.1))

            if not self._cancelled:
                await self._emit_complete()
        finally:
            self._decoder.unsubscribe(collector)
            collector_task.cancel()
            try:
                await collector_task
            except asyncio.CancelledError:
                pass
            self._log.info("Rehearsal finished")

    async def stop(self) -> None:
        """
        Request cancellation of an active rehearsal run.

        Cancels the background task if one is running.
        """
        self._cancelled = True
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._log.info("Rehearsal stop requested")

    def start_background(self, speed_multiplier: float = 3.0) -> asyncio.Task[None]:
        """
        Start rehearsal as a background asyncio task.

        Args:
            speed_multiplier: Playback speed multiplier.

        Returns:
            The created asyncio.Task.
        """
        self._task = asyncio.create_task(self.run(speed_multiplier=speed_multiplier))
        return self._task

    def get_progress(self) -> dict[str, int | float]:
        """
        Return current rehearsal progress metrics.

        Returns:
            Dict with current_event, total_events, current_lap, elapsed_seconds.
        """
        elapsed = 0.0
        if self._started_at is not None:
            elapsed = time.perf_counter() - self._started_at
        return {
            "current_event": self._current_event,
            "total_events": len(self._scenario.events),
            "current_lap": self._current_lap,
            "elapsed_seconds": round(elapsed, 1),
        }

    async def _emit_complete(self) -> None:
        """Broadcast REHEARSAL_COMPLETE summary to all decoder subscribers."""
        transmissions = self._decoded_transmissions
        latencies = [
            t.processing_latency_ms
            for t in transmissions
            if t.processing_latency_ms is not None
        ]
        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
        intel_count = sum(1 for t in transmissions if t.competitor_intel is not None)
        urgency_breakdown: dict[str, int] = {level.value: 0 for level in UrgencyLevel}
        for transmission in transmissions:
            urgency_breakdown[transmission.urgency_level.value] += 1

        payload = {
            "scenario": self._scenario.name,
            "circuit": self._scenario.circuit,
            "total_transmissions": len(transmissions),
            "avg_latency_ms": round(avg_latency, 1),
            "competitor_intel_count": intel_count,
            "urgency_breakdown": urgency_breakdown,
        }
        await self._decoder.broadcast_event(
            WebSocketEvent(
                event_type=StreamEventType.REHEARSAL_COMPLETE,
                payload=payload,
                session_key=self._decoder._deps.session_key,
                emitted_at=datetime.now(tz=UTC),
            )
        )
