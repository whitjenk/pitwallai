"""Async runtime for ingesting OpenF1 radio and emitting decoded transmissions."""

from __future__ import annotations

import asyncio
import json
import random
from datetime import UTC, datetime
from typing import Any

import websockets
import websockets.exceptions
from loguru import logger
from pydantic import ValidationError

from pitwallai.agents.radio_intercept.agent import RadioInterceptAgent
from pitwallai.agents.radio_intercept.errors import DecodeRuntimeError, DecodeValidationError
from pitwallai.agents.radio_intercept.enums import (
    ConfirmationState,
    RadioIntent,
    StreamEventType,
    UrgencyLevel,
)
from pitwallai.agents.radio_intercept.models import (
    AgentDependencies,
    DecodedTransmission,
    RadioRawMessage,
    WebSocketEvent,
)
from pitwallai.agents.radio_intercept.seed_data import JARGON_GLOSSARY, TEAM_COLORS
from pitwallai.agents.radio_intercept.vector_store import MockVectorStore

_DRIVER_NUMBER_TO_CODE: dict[int, tuple[str, str]] = {
    1: ("VER", "Red Bull Racing"),
    44: ("HAM", "Mercedes"),
    4: ("NOR", "McLaren"),
    16: ("LEC", "Ferrari"),
    55: ("SAI", "Ferrari"),
    63: ("RUS", "Mercedes"),
}


class RadioInterceptDecoder:
    """
    Top-level async runtime for the Radio Intercept Decoder pipeline.

    Ingests OpenF1 WebSocket team radio frames, decodes them via the Pydantic AI agent,
    and fans out structured DecodedTransmission results to subscriber queues.
    """

    def __init__(
        self,
        agent: RadioInterceptAgent,
        vector_store: MockVectorStore,
        openf1_ws_url: str = "wss://api.openf1.org/v1/team_radio",
        max_queue_depth: int = 50,
        backpressure_drop_below: UrgencyLevel = UrgencyLevel.HIGH,
    ) -> None:
        """
        Initialize the radio intercept decoder runtime.

        Args:
            agent: Configured RadioInterceptAgent instance.
            vector_store: Seeded mock vector store for historical context.
            openf1_ws_url: OpenF1 team radio WebSocket endpoint.
            max_queue_depth: Input queue depth before backpressure applies.
            backpressure_drop_below: Drop inbound messages below this urgency when queue is full.
        """
        self._agent = agent
        self._vector_store = vector_store
        self._openf1_ws_url = openf1_ws_url
        self._max_queue_depth = max_queue_depth
        self._backpressure_drop_below = backpressure_drop_below
        self._input_queue: asyncio.Queue[RadioRawMessage | None] = asyncio.Queue()
        self._output_queue: asyncio.Queue[DecodedTransmission] = asyncio.Queue()
        self._subscribers: list[asyncio.Queue[WebSocketEvent]] = []
        self._running = False
        self._deps = AgentDependencies(
            vector_store=vector_store,
            session_key=0,
            jargon_glossary=JARGON_GLOSSARY,
            team_colors=TEAM_COLORS,
        )
        self._log = logger

    async def run(self) -> None:
        """
        Start the WebSocket producer, agent consumer, and output emitter concurrently.

        Runs until cancelled or stopped. Handles CancelledError with clean shutdown logging.

        Raises:
            Exception: Propagates unrecoverable producer failures after reconnect exhaustion.
        """
        self._running = True
        self._log.info("RadioInterceptDecoder starting")
        try:
            await asyncio.gather(
                self._ws_producer(),
                self._agent_consumer(),
                self._output_emitter(),
            )
        except asyncio.CancelledError:
            self._running = False
            self._log.info("RadioInterceptDecoder cancelled — shutting down")
            raise
        finally:
            self._running = False

    async def stop(self) -> None:
        """
        Signal the decoder to stop and unblock the consumer with a sentinel.

        Sets the running flag false and enqueues None on the input queue.
        """
        self._running = False
        await self._input_queue.put(None)
        self._log.info("RadioInterceptDecoder stop requested")

    def subscribe(self, subscriber_queue: asyncio.Queue[WebSocketEvent]) -> None:
        """
        Register a queue to receive WebSocket event fan-out.

        Args:
            subscriber_queue: Async queue that will receive WebSocketEvent instances.
        """
        if subscriber_queue not in self._subscribers:
            self._subscribers.append(subscriber_queue)

    def unsubscribe(self, subscriber_queue: asyncio.Queue[WebSocketEvent]) -> None:
        """
        Remove a subscriber queue from fan-out.

        Args:
            subscriber_queue: Previously registered subscriber queue.
        """
        if subscriber_queue in self._subscribers:
            self._subscribers.remove(subscriber_queue)

    async def broadcast_event(self, event: WebSocketEvent) -> None:
        """
        Fan out a WebSocket event to all subscribers without going through the decode pipeline.

        Args:
            event: Event envelope to broadcast.
        """
        for subscriber_queue in list(self._subscribers):
            try:
                subscriber_queue.put_nowait(event)
            except asyncio.QueueFull:
                self._log.warning(
                    "Subscriber queue full — skipping fan-out to one subscriber"
                )

    def _resolve_driver(self, payload: dict[str, Any]) -> tuple[str, str]:
        """
        Resolve driver code and team from payload or driver number lookup.

        Args:
            payload: Raw OpenF1 JSON payload.

        Returns:
            Tuple of (driver_code, team name).
        """
        if payload.get("driver_code") and payload.get("team"):
            return str(payload["driver_code"]), str(payload["team"])

        driver_number = payload.get("driver_number")
        if driver_number is not None:
            mapping = _DRIVER_NUMBER_TO_CODE.get(int(driver_number))
            if mapping:
                return mapping

        return (
            str(payload.get("driver_code", "UNK")),
            str(payload.get("team", "Unknown")),
        )

    def _parse_openf1_frame(self, raw: str) -> RadioRawMessage | None:
        """
        Parse a WebSocket JSON frame into a RadioRawMessage.

        Args:
            raw: Raw WebSocket message string.

        Returns:
            Validated RadioRawMessage, or None if parsing fails.
        """
        try:
            payload: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            self._log.warning("Skipping non-JSON WebSocket frame")
            return None

        transcript = (
            payload.get("transcript")
            or payload.get("message")
            or payload.get("raw_transcript")
            or payload.get("radio_text")
            or ""
        )
        if not str(transcript).strip():
            return None

        timestamp_raw = payload.get("timestamp") or payload.get("date")
        if isinstance(timestamp_raw, str):
            timestamp = datetime.fromisoformat(timestamp_raw.replace("Z", "+00:00"))
        elif isinstance(timestamp_raw, datetime):
            timestamp = timestamp_raw
        else:
            timestamp = datetime.now(tz=UTC)

        driver_code, team = self._resolve_driver(payload)

        try:
            return RadioRawMessage(
                session_key=int(payload.get("session_key", 0)),
                driver_number=int(payload.get("driver_number", 0)),
                driver_code=driver_code,
                team=team,
                timestamp=timestamp,
                raw_transcript=str(transcript),
                recording_url=payload.get("recording_url"),
            )
        except (ValidationError, ValueError, TypeError) as exc:
            self._log.bind(payload_keys=list(payload.keys())).warning(
                "Invalid OpenF1 frame: {}", exc
            )
            return None

    async def _ws_producer(self) -> None:
        """
        Connect to OpenF1 WebSocket and enqueue validated radio messages.

        Applies backpressure dropping when the input queue is full. Reconnects with
        exponential backoff on connection loss.

        Raises:
            ConnectionError: After maximum reconnect attempts are exhausted.
        """
        reconnect_attempt = 0
        max_attempts = 10
        base_delay = 1.0
        max_delay = 30.0

        while self._running:
            try:
                async with websockets.connect(
                    self._openf1_ws_url,
                    ping_interval=20,
                    ping_timeout=10,
                ) as websocket:
                    reconnect_attempt = 0
                    self._log.bind(url=self._openf1_ws_url).info(
                        "OpenF1 WebSocket connected"
                    )
                    async for frame in websocket:
                        if not self._running:
                            break

                        message = self._parse_openf1_frame(frame)
                        if message is None:
                            continue

                        if self._input_queue.qsize() >= self._max_queue_depth:
                            inferred_urgency = UrgencyLevel.from_intent(RadioIntent.UNKNOWN)
                            if inferred_urgency.priority < self._backpressure_drop_below.priority:
                                self._log.bind(
                                    driver=message.driver_code,
                                    session=message.session_key,
                                    queue_depth=self._input_queue.qsize(),
                                ).warning(
                                    "Backpressure: dropping low-urgency message"
                                )
                                continue

                        self._deps.session_key = message.session_key
                        await self._input_queue.put(message)

            except websockets.exceptions.ConnectionClosed as exc:
                self._log.bind(url=self._openf1_ws_url).warning(
                    "OpenF1 WebSocket closed: {}", exc
                )
            except Exception as exc:
                self._log.bind(url=self._openf1_ws_url).warning(
                    "OpenF1 WebSocket error: {}", exc
                )

            if not self._running:
                break

            reconnect_attempt += 1
            if reconnect_attempt > max_attempts:
                raise ConnectionError(
                    f"OpenF1 WebSocket reconnect failed after {max_attempts} attempts"
                )

            delay = min(base_delay * (2.0 ** (reconnect_attempt - 1)), max_delay)
            jitter = random.uniform(-0.5, 0.5)
            sleep_for = max(0.1, delay + jitter)
            self._log.bind(attempt=reconnect_attempt, sleep_s=sleep_for).warning(
                "Reconnecting OpenF1 WebSocket"
            )
            await asyncio.sleep(sleep_for)

    async def _agent_consumer(self) -> None:
        """
        Consume raw messages from the input queue and decode via the agent.

        Skips messages that fail validation or runtime decode without crashing the loop.
        """
        while self._running:
            msg = await self._input_queue.get()
            try:
                if msg is None:
                    break

                self._deps.session_key = msg.session_key
                result = await self._agent.decode(msg, self._deps)
                await self._output_queue.put(result)
            except DecodeValidationError as exc:
                self._log.bind(
                    driver=msg.driver_code if msg else "unknown",
                ).error("Decode validation error, skipping: {}", exc)
            except DecodeRuntimeError as exc:
                self._log.error("Decode runtime error, skipping: {}", exc)
            finally:
                self._input_queue.task_done()

    async def _output_emitter(self) -> None:
        """
        Fan out decoded transmissions to all subscriber queues.

        Uses a 1-second wait timeout to periodically check the running flag.
        """
        while self._running:
            try:
                result = await asyncio.wait_for(self._output_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            emitted_at = datetime.now(tz=UTC)
            events: list[WebSocketEvent] = [
                WebSocketEvent(
                    event_type=StreamEventType.TRANSMISSION_DECODED,
                    payload=result,
                    session_key=self._deps.session_key,
                    emitted_at=emitted_at,
                )
            ]
            if result.exceeds_latency_target:
                events.append(
                    WebSocketEvent(
                        event_type=StreamEventType.LATENCY_BREACH,
                        payload={
                            "latency_ms": result.processing_latency_ms,
                            "driver": result.driver_code,
                        },
                        session_key=self._deps.session_key,
                        emitted_at=emitted_at,
                    )
                )
            if (
                result.competitor_intel is not None
                and result.competitor_intel.confirmation_state
                == ConfirmationState.UNCONFIRMED
            ):
                events.append(
                    WebSocketEvent(
                        event_type=StreamEventType.COMPETITOR_INTEL_UNCONFIRMED,
                        payload=result,
                        session_key=self._deps.session_key,
                        emitted_at=emitted_at,
                    )
                )

            for event in events:
                await self.broadcast_event(event)

            latency_ms = result.processing_latency_ms or 0.0
            self._log.bind(
                driver=result.driver_code,
                session=result.session_key,
                intent=result.decoded_intent.value,
                urgency=result.urgency_level.value,
                latency_ms=round(latency_ms, 1),
            ).info("Emitted decoded transmission")

            self._output_queue.task_done()


def _mock_messages() -> list[RadioRawMessage]:
    """
    Build demo RadioRawMessage fixtures for offline testing.

    Returns:
        List of three realistic mock radio messages.
    """
    base_time = datetime(2024, 5, 26, 14, 30, 0, tzinfo=UTC)
    return [
        RadioRawMessage(
            session_key=9158,
            driver_number=1,
            driver_code="VER",
            team="Red Bull Racing",
            timestamp=base_time,
            raw_transcript="Box, box, box. Pit confirm.",
            recording_url=None,
        ),
        RadioRawMessage(
            session_key=9158,
            driver_number=44,
            driver_code="HAM",
            team="Mercedes",
            timestamp=base_time,
            raw_transcript="Tyres are gone, mate. Front left is dead.",
            recording_url=None,
        ),
        RadioRawMessage(
            session_key=9158,
            driver_number=4,
            driver_code="NOR",
            team="McLaren",
            timestamp=base_time,
            raw_transcript="Push, push, push. Deploy full ERS.",
            recording_url=None,
        ),
    ]


async def main() -> None:
    """
    Runnable demo: decode three mock transmissions without a live WebSocket.

    Creates vector store and agent, feeds mock messages directly to the input queue,
    runs consumer and emitter coroutines, and prints JSON results.
    """
    vector_store = MockVectorStore()
    agent = RadioInterceptAgent()
    decoder = RadioInterceptDecoder(agent=agent, vector_store=vector_store)

    subscriber: asyncio.Queue[WebSocketEvent] = asyncio.Queue(maxsize=10)
    decoder.subscribe(subscriber)
    decoder._running = True
    decoder._deps.session_key = 9158

    consumer_task = asyncio.create_task(decoder._agent_consumer())
    emitter_task = asyncio.create_task(decoder._output_emitter())

    for mock in _mock_messages():
        decoder._deps.session_key = mock.session_key
        await decoder._input_queue.put(mock)

    await decoder._input_queue.put(None)

    try:
        await asyncio.wait_for(
            asyncio.gather(consumer_task, emitter_task),
            timeout=30.0,
        )
    except asyncio.TimeoutError:
        consumer_task.cancel()
        emitter_task.cancel()
        raise

    results: list[DecodedTransmission] = []
    while len(results) < 3:
        event = await subscriber.get()
        if event.event_type == StreamEventType.TRANSMISSION_DECODED and isinstance(
            event.payload, DecodedTransmission
        ):
            results.append(event.payload)

    for item in results:
        print(item.model_dump_json(indent=2))

    await decoder.stop()


if __name__ == "__main__":
    asyncio.run(main())
