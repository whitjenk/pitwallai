"""Resilience tests for the radio intercept consumer pipeline."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from pitwallai.agents.radio_intercept.agent import DecodeRuntimeError, DecodeValidationError
from pitwallai.agents.radio_intercept.enums import RadioIntent, StrategicSignal, UrgencyLevel
from pitwallai.agents.radio_intercept.models import (
    DecodedTransmission,
    JargonEntry,
    RadioRawMessage,
    WebSocketEvent,
)
from pitwallai.agents.radio_intercept.seed_data import MONACO_REHEARSAL_SCENARIO


def _valid_message(transcript: str = "Gap is 2.1") -> RadioRawMessage:
    """Build a minimal valid radio message."""
    return RadioRawMessage(
        session_key=9158,
        driver_number=4,
        driver_code="NOR",
        team="McLaren",
        timestamp=datetime.now(tz=UTC),
        raw_transcript=transcript,
    )


def _mock_decoded(message: RadioRawMessage) -> DecodedTransmission:
    """Build a minimal decoded transmission for mocks."""
    return DecodedTransmission(
        session_key=message.session_key,
        driver_number=message.driver_number,
        driver_code=message.driver_code,
        team=message.team,
        timestamp=message.timestamp,
        raw_transcript=message.raw_transcript,
        decoded_intent=RadioIntent.GAP_UPDATE_REQUEST,
        jargon_decoded=[],
        strategic_signal=StrategicSignal.NEUTRAL,
        urgency_level=UrgencyLevel.LOW,
        confidence_score=0.8,
        competitor_intel=None,
        evidence_summary=None,
        team_color="#FF8000",
        context_doc_ids=[],
        model_reasoning="test",
    )


def test_empty_transcript_is_skipped() -> None:
    """Empty transcripts fail validation before enqueue."""
    with pytest.raises(ValidationError):
        RadioRawMessage(
            session_key=9158,
            driver_number=4,
            driver_code="NOR",
            team="McLaren",
            timestamp=datetime.now(tz=UTC),
            raw_transcript="   ",
        )


@pytest.mark.asyncio
async def test_decode_validation_error_does_not_crash_consumer(decoder) -> None:
    """DecodeValidationError skips message without stopping consumer."""
    messages = [_valid_message(f"msg {i}") for i in range(3)]

    with patch.object(
        decoder._agent,
        "decode",
        AsyncMock(side_effect=DecodeValidationError("bad")),
    ):
        consumer = asyncio.create_task(decoder._agent_consumer())
        for msg in messages:
            await decoder._input_queue.put(msg)
        await decoder._input_queue.put(None)
        await asyncio.wait_for(consumer, timeout=5.0)

    assert decoder._output_queue.qsize() == 0


@pytest.mark.asyncio
async def test_decode_runtime_error_does_not_crash_consumer(decoder) -> None:
    """First runtime error skipped; second message decoded."""
    msg1 = _valid_message("first")
    msg2 = _valid_message("second")
    decoded = _mock_decoded(msg2)

    with patch.object(
        decoder._agent,
        "decode",
        AsyncMock(side_effect=[DecodeRuntimeError("fail"), decoded]),
    ):
        consumer = asyncio.create_task(decoder._agent_consumer())
        await decoder._input_queue.put(msg1)
        await decoder._input_queue.put(msg2)
        await decoder._input_queue.put(None)
        await asyncio.wait_for(consumer, timeout=5.0)

    assert decoder._output_queue.qsize() == 1


@pytest.mark.asyncio
async def test_sentinel_stops_consumer_cleanly(decoder) -> None:
    """None sentinel stops the consumer promptly."""
    decoder._running = True
    consumer = asyncio.create_task(decoder._agent_consumer())
    await decoder._input_queue.put(None)
    await asyncio.wait_for(consumer, timeout=2.0)
    await decoder.stop()
    assert decoder._running is False


@pytest.mark.asyncio
async def test_malformed_json_frame_is_skipped_in_producer(decoder) -> None:
    """Invalid JSON is skipped; valid frame is enqueued."""

    class FakeWS:
        def __init__(self, frames: list[str]) -> None:
            self._frames = frames

        def __aiter__(self):
            return self

        async def __anext__(self) -> str:
            if not self._frames:
                raise StopAsyncIteration
            return self._frames.pop(0)

    valid_payload = {
        "session_key": 9158,
        "driver_number": 4,
        "driver_code": "NOR",
        "team": "McLaren",
        "date": datetime.now(tz=UTC).isoformat(),
        "transcript": "Valid frame after bad json",
    }

    decoder._running = True

    with patch("pitwallai.agents.radio_intercept.stream_handler.websockets.connect") as mock_connect:
        mock_connect.return_value.__aenter__.return_value = FakeWS(
            ["not json", json.dumps(valid_payload)]
        )
        producer = asyncio.create_task(decoder._ws_producer())
        try:
            msg = await asyncio.wait_for(decoder._input_queue.get(), timeout=3.0)
            assert msg is not None
            assert "Valid frame" in msg.raw_transcript
        finally:
            decoder._running = False
            producer.cancel()
            try:
                await producer
            except asyncio.CancelledError:
                pass
