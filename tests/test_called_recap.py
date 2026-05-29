"""Tests for the post-race 'what we called' recap."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from intelligence.called_recap import (
    build_called_recap,
    recap_from_json,
    recap_to_json,
    render_called_recap_whatsapp,
)
from intelligence.called_recap_page import render_called_recap_share_html
from orchestrator.race_context import RaceEvent, RaceEventType


def _event(
    *,
    event_type: RaceEventType = RaceEventType.SAFETY_CAR,
    lap: int | None = 23,
    driver_code: str | None = None,
    src_seconds_ago: float = 30.0,
    decode_latency_seconds: float = 4.0,
    description: str = "SC deployed turn 7 debris",
) -> RaceEvent:
    now = datetime.now(tz=UTC)
    src = now - timedelta(seconds=src_seconds_ago)
    decoded = src + timedelta(seconds=decode_latency_seconds)
    return RaceEvent(
        race_key="2026_test",
        event_type=event_type,
        lap=lap,
        description=description,
        utc_timestamp=src,
        driver_code=driver_code,
        decoded_at_utc=decoded,
    )


def test_decode_latency_seconds_property() -> None:
    ev = _event(decode_latency_seconds=3.5)
    assert ev.decode_latency_seconds is not None
    assert abs(ev.decode_latency_seconds - 3.5) < 0.01


def test_decode_latency_none_when_decoded_at_missing() -> None:
    ev = RaceEvent(
        race_key="r",
        event_type=RaceEventType.SAFETY_CAR,
        lap=1,
        description="x",
        utc_timestamp=datetime.now(tz=UTC),
    )
    assert ev.decode_latency_seconds is None


def test_recap_filters_to_strategic_event_types() -> None:
    events = [
        _event(event_type=RaceEventType.SAFETY_CAR, lap=23),
        _event(event_type=RaceEventType.RACE_COMPLETE, lap=None),
        _event(event_type=RaceEventType.WEATHER_CHANGE, lap=10),
        _event(event_type=RaceEventType.RETIREMENT, lap=40, driver_code="HAM"),
    ]
    recap = build_called_recap(
        race_key="2026_test", race_label="Test GP", events=events
    )
    assert recap.moment_count == 2
    types = {m.event_type for m in recap.moments}
    assert types == {RaceEventType.SAFETY_CAR, RaceEventType.RETIREMENT}


def test_median_decode_latency() -> None:
    events = [
        _event(decode_latency_seconds=2.0),
        _event(decode_latency_seconds=5.0),
        _event(decode_latency_seconds=11.0),
    ]
    recap = build_called_recap(
        race_key="2026_test", race_label="Test GP", events=events
    )
    assert recap.median_decode_latency_seconds == 5.0


def test_quiet_race_whatsapp_message() -> None:
    """Quiet races render as a verdict ('moments that mattered'), not as
    missing data — see the quieter-framing rework."""
    recap = build_called_recap(
        race_key="2026_test", race_label="Test GP", events=[]
    )
    msg = render_called_recap_whatsapp(recap, share_url=None)
    assert "zero strategic moments" in msg
    assert "Not financial advice" in msg


def test_whatsapp_message_includes_share_url_when_provided() -> None:
    events = [_event(lap=18, driver_code="VER")]
    recap = build_called_recap(
        race_key="2026_test", race_label="Test GP", events=events
    )
    msg = render_called_recap_whatsapp(recap, share_url="https://x.test/called/abc")
    assert "https://x.test/called/abc" in msg
    assert "L18" in msg


def test_share_page_renders_with_evidence_timestamps() -> None:
    events = [
        _event(lap=23, driver_code="LEC"),
        _event(event_type=RaceEventType.RED_FLAG, lap=41, driver_code=None),
    ]
    recap = build_called_recap(
        race_key="2026_test", race_label="Test GP", events=events
    )
    html = render_called_recap_share_html(recap)
    assert "<!doctype html>" in html
    assert "Test GP" in html
    assert "Source signal" in html
    assert "decoded" in html
    assert "L23" in html
    assert "LEC" in html


def test_share_page_empty_state() -> None:
    """Empty share page also reads as a verdict, not an absence."""
    recap = build_called_recap(
        race_key="2026_test", race_label="Test GP", events=[]
    )
    html = render_called_recap_share_html(recap)
    assert "moments that mattered" in html


def test_json_round_trip_preserves_moments() -> None:
    events = [
        _event(lap=23, driver_code="LEC"),
        _event(event_type=RaceEventType.RED_FLAG, lap=41),
    ]
    recap = build_called_recap(
        race_key="2026_test", race_label="Test GP", events=events
    )
    restored = recap_from_json(recap_to_json(recap))
    assert restored.race_key == recap.race_key
    assert restored.race_label == recap.race_label
    assert restored.share_token == recap.share_token
    assert len(restored.moments) == len(recap.moments)
    assert restored.moments[0].driver_code == "LEC"
    assert restored.moments[1].event_type == RaceEventType.RED_FLAG
