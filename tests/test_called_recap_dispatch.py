"""Tests for the Sunday-night called-recap dispatch in scorer_learner."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from agents.scorer_learner import _broadcast_called_recap
from intelligence.called_recap import CalledRaceRecap, CalledMoment
from orchestrator.race_context import RaceEventType


def _ctx_stub(race_key: str = "2026_test", display_name: str = "Test GP"):
    """Minimal stub of RaceContext for the dispatch function.

    We only access ctx.race_weekend.race_key and .display_name, so a
    namespace object is enough — keeps the test independent of the
    full RaceContext / RaceWeekend Pydantic constructor surface.
    """
    from types import SimpleNamespace

    return SimpleNamespace(
        race_weekend=SimpleNamespace(
            race_key=race_key,
            display_name=display_name,
        )
    )


@pytest.mark.asyncio
async def test_quiet_race_skips_dispatch_entirely() -> None:
    """No moments → no WhatsApp message goes out (avoid spam)."""
    quiet = CalledRaceRecap(
        race_key="2026_test",
        race_label="Test GP",
        moments=(),
        share_token="tok",
    )

    with (
        patch(
            "intelligence.called_recap.generate_and_persist_called_recap",
            new=AsyncMock(return_value=quiet),
        ),
        patch(
            "agents.scorer_learner.list_subscribers_for_race_picks",
            new=AsyncMock(return_value=[]),
        ) as list_subs,
        patch("agents.scorer_learner.send_message", new=AsyncMock()) as sender,
    ):
        await _broadcast_called_recap(_ctx_stub())
        # No subscriber lookup either — the early return must fire first.
        list_subs.assert_not_called()
        sender.assert_not_called()


@pytest.mark.asyncio
async def test_busy_race_sends_to_full_cadence_only() -> None:
    """FULL subscribers get the message; RACE_DAY_ONLY are skipped."""
    busy = CalledRaceRecap(
        race_key="2026_test",
        race_label="Test GP",
        moments=(
            CalledMoment(
                event_type=RaceEventType.SAFETY_CAR,
                lap=23,
                driver_code=None,
                description="SC deployed turn 7 debris",
                source_signal_utc=datetime.now(tz=UTC) - timedelta(seconds=30),
                decoded_at_utc=datetime.now(tz=UTC) - timedelta(seconds=26),
                decode_latency_seconds=4.0,
            ),
        ),
        share_token="tok-busy",
    )

    from types import SimpleNamespace

    subs = [
        SimpleNamespace(phone="+10000000001", cadence_preference="FULL"),
        SimpleNamespace(phone="+10000000002", cadence_preference="RACE_DAY_ONLY"),
        SimpleNamespace(phone="+10000000003", cadence_preference="FULL"),
    ]

    with (
        patch(
            "intelligence.called_recap.generate_and_persist_called_recap",
            new=AsyncMock(return_value=busy),
        ),
        patch(
            "agents.scorer_learner.list_subscribers_for_race_picks",
            new=AsyncMock(return_value=subs),
        ),
        patch("agents.scorer_learner.send_message", new=AsyncMock()) as sender,
    ):
        await _broadcast_called_recap(_ctx_stub())

    # Two FULL subscribers, zero RACE_DAY_ONLY.
    assert sender.await_count == 2
    sent_phones = {call.args[0] for call in sender.await_args_list}
    assert sent_phones == {"+10000000001", "+10000000003"}
    sent_body = sender.await_args_list[0].args[1]
    assert "what we called" in sent_body.lower()
    assert "https://pitwallai.app/called/tok-busy" in sent_body


@pytest.mark.asyncio
async def test_build_failure_does_not_raise() -> None:
    """A recap-build exception must not block the scorer pipeline."""
    with (
        patch(
            "intelligence.called_recap.generate_and_persist_called_recap",
            new=AsyncMock(side_effect=RuntimeError("db down")),
        ),
        patch(
            "agents.scorer_learner.list_subscribers_for_race_picks",
            new=AsyncMock(return_value=[]),
        ),
        patch("agents.scorer_learner.send_message", new=AsyncMock()) as sender,
    ):
        # Must not raise.
        await _broadcast_called_recap(_ctx_stub())
        sender.assert_not_called()
