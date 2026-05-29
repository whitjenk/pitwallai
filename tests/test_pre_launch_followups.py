"""Tests for the pre-launch follow-up bundle:
cost cuts (message bundling), quieter quiet-race framing, verify guard,
onboarding metrics, and subscriber-count threshold on the homepage."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

from intelligence.called_recap import (
    CalledRaceRecap,
    render_called_recap_whatsapp,
)
from intelligence.called_recap_page import render_called_recap_share_html
from intelligence.homepage import render_homepage_html


# ── Quieter quiet-race framing ────────────────────────────────────────────


def test_quiet_race_whatsapp_reads_as_verdict_not_absence() -> None:
    """Empty recap must frame as a verdict ('moments that mattered') so a
    Monaco-style processional race doesn't read as missing data."""
    quiet = CalledRaceRecap(
        race_key="r", race_label="Monaco GP", moments=(), share_token="t",
    )
    msg = render_called_recap_whatsapp(quiet, share_url=None)
    assert "zero strategic moments" in msg
    assert "verdict, not an absence" in msg
    # The old absence-framing language must be gone.
    assert "No strategic call-outs" not in msg


def test_quiet_race_share_page_reads_as_verdict() -> None:
    quiet = CalledRaceRecap(
        race_key="r", race_label="Monaco GP", moments=(), share_token="t",
    )
    html = render_called_recap_share_html(quiet)
    assert "moments that mattered" in html
    assert "verdict, not an absence" in html


# ── Verify-in-app guard on chip/transfer messages ─────────────────────────


def test_chip_message_helper_appends_verify_guard() -> None:
    """All chip / transfer messages must carry the verify-in-app guard so
    a stale rules snapshot in fantasy/rules.py can't mislead a user."""
    from whatsapp.phase7 import _VERIFY_GUARD, _with_verify_guard

    out = _with_verify_guard("hello", limit=300)
    assert _VERIFY_GUARD in out
    assert out.endswith(_VERIFY_GUARD)


def test_verify_guard_fits_when_body_overflows() -> None:
    """Guard is non-negotiable — body is truncated to make room."""
    from whatsapp.phase7 import _VERIFY_GUARD, _with_verify_guard

    out = _with_verify_guard("x" * 1000, limit=120)
    assert _VERIFY_GUARD in out
    assert len(out) <= 120


def test_chips_share_page_carries_verify_guard() -> None:
    from datetime import UTC, datetime

    from intelligence.chip_planner import ChipPlan
    from intelligence.chips_page import render_chips_share_html

    plan = ChipPlan(
        windows=[],
        recommended_sequence=[],
        sprint_warnings=[],
        mini_league_windows=[],
        generated_at=datetime.now(tz=UTC),
        share_token="t",
    )
    html = render_chips_share_html(plan)
    assert "Verify in the F1 Fantasy app" in html


# ── Chip-planner honest framing (no false-precision "confidence %") ───────


def test_chips_share_page_frames_as_circuit_fit_not_probability() -> None:
    """The window score is a circuit heuristic — the page must say 'circuit
    fit' and carry the not-a-projection disclaimer, never imply a model
    probability."""
    from datetime import UTC, datetime

    from intelligence.chip_conviction import ConfidenceTier
    from intelligence.chip_planner import ChipPlan, ChipType, ChipWindow
    from intelligence.chips_page import render_chips_share_html

    plan = ChipPlan(
        windows=[
            ChipWindow(
                race_key="2026_monaco",
                circuit_key="monaco",
                race_name="Monaco Grand Prix",
                race_utc=datetime(2026, 5, 24, 13, 0, tzinfo=UTC),
                is_sprint=False,
                championship_week=2,
                recommended_chips=[ChipType.LIMITLESS],
                reasoning="high overtaking difficulty",
                confidence=0.82,
                priority="HIGH",
                confidence_tier=ConfidenceTier.HIGH,
                confidence_reasons=["high overtaking difficulty"],
            )
        ],
        recommended_sequence=[("limitless", "2026_monaco")],
        sprint_warnings=[],
        mini_league_windows=[],
        generated_at=datetime.now(tz=UTC),
        share_token="t",
    )
    html = render_chips_share_html(plan)
    assert "circuit fit" in html
    assert "not a points projection" in html
    assert "heuristic guide" in html
    # No raw confidence percentage leaked into the rendered page.
    assert "82%" not in html


@pytest.mark.asyncio
async def test_chip_detail_message_uses_fit_tier_not_percentage() -> None:
    """CHIPS <chip> reply must show a fit tier, not a false-precision %."""
    from datetime import UTC, datetime
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    from intelligence.chip_conviction import ConfidenceTier
    from intelligence.chip_planner import ChipPlan, ChipType, ChipWindow

    team = SimpleNamespace(chips_used={})
    window = ChipWindow(
        race_key="2026_monaco",
        circuit_key="monaco",
        race_name="Monaco Grand Prix",
        race_utc=datetime(2026, 5, 24, 13, 0, tzinfo=UTC),
        is_sprint=False,
        championship_week=2,
        recommended_chips=[ChipType.LIMITLESS],
        reasoning="high overtaking difficulty",
        confidence=0.82,
        priority="HIGH",
        confidence_tier=ConfidenceTier.HIGH,
        confidence_reasons=["high overtaking difficulty"],
    )
    plan = ChipPlan(
        windows=[window],
        recommended_sequence=[],
        sprint_warnings=[],
        mini_league_windows=[],
        generated_at=datetime.now(tz=UTC),
        share_token="t",
    )
    with (
        patch("whatsapp.phase7.get_fantasy_team", new=AsyncMock(return_value=team)),
        patch("whatsapp.phase7.chip_available", return_value=True),
        patch("whatsapp.phase7.generate_chip_plan", return_value=plan),
        patch("whatsapp.phase7.remaining_races_from_now", return_value=[]),
    ):
        from whatsapp.phase7 import send_chip_detail

        msg = await send_chip_detail("+10000000001", "limitless")

    assert "Circuit fit: HIGH" in msg
    assert "%" not in msg  # no false-precision percentage


# ── Cost cut: Sunday message bundling ─────────────────────────────────────


@pytest.mark.asyncio
async def test_build_called_recap_tail_returns_text_for_busy_race() -> None:
    """The new tail builder must return formatted text for race with moments
    — the scorer broadcast bundles it into the per-user recap message."""
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from agents.scorer_learner import _build_called_recap_tail
    from intelligence.called_recap import CalledMoment
    from orchestrator.race_context import RaceEventType

    busy = CalledRaceRecap(
        race_key="r",
        race_label="Test GP",
        moments=(
            CalledMoment(
                event_type=RaceEventType.SAFETY_CAR,
                lap=23, driver_code=None, description="SC debris",
                source_signal_utc=datetime.now(tz=UTC) - timedelta(seconds=30),
                decoded_at_utc=datetime.now(tz=UTC) - timedelta(seconds=26),
                decode_latency_seconds=4.0,
            ),
        ),
        share_token="tok-A",
    )
    ctx = SimpleNamespace(
        race_weekend=SimpleNamespace(race_key="r", display_name="Test GP")
    )
    with patch(
        "intelligence.called_recap.generate_and_persist_called_recap",
        new=AsyncMock(return_value=busy),
    ):
        tail = await _build_called_recap_tail(ctx)
    assert tail is not None
    assert "what we called" in tail.lower()
    assert "https://pitwallai.app/called/tok-A" in tail


@pytest.mark.asyncio
async def test_build_called_recap_tail_returns_verdict_for_quiet_race() -> None:
    """Quiet races now ride along with the recap as a verdict, not skipped.
    That keeps the brand "we count what mattered" visible every weekend."""
    from types import SimpleNamespace

    from agents.scorer_learner import _build_called_recap_tail

    quiet = CalledRaceRecap(
        race_key="r", race_label="Monaco GP", moments=(), share_token="t",
    )
    ctx = SimpleNamespace(
        race_weekend=SimpleNamespace(race_key="r", display_name="Monaco GP")
    )
    with patch(
        "intelligence.called_recap.generate_and_persist_called_recap",
        new=AsyncMock(return_value=quiet),
    ):
        tail = await _build_called_recap_tail(ctx)
    assert tail is not None
    assert "zero strategic moments" in tail


@pytest.mark.asyncio
async def test_build_called_recap_tail_returns_none_on_failure() -> None:
    """Failures must never block the season-recap pipeline."""
    from types import SimpleNamespace

    from agents.scorer_learner import _build_called_recap_tail

    ctx = SimpleNamespace(
        race_weekend=SimpleNamespace(race_key="r", display_name="Test GP")
    )
    with patch(
        "intelligence.called_recap.generate_and_persist_called_recap",
        new=AsyncMock(side_effect=RuntimeError("db down")),
    ):
        tail = await _build_called_recap_tail(ctx)
    assert tail is None


# ── Subscriber-count threshold on homepage ────────────────────────────────


def test_homepage_hides_raw_count_below_threshold() -> None:
    """A '23 subscribers' figure publicly is worse than no number — it
    anchors the brand to volatile early data."""
    html = render_homepage_html(
        {
            "active_subscribers": 23,
            "season_hit_rate_pct": 64.0,
            "races_scored": 7,
            "scored_picks": 28,
        }
    )
    assert ">Early<" in html
    assert "invite-only ramp" in html
    assert ">23<" not in html


def test_homepage_reveals_raw_count_above_threshold() -> None:
    html = render_homepage_html(
        {
            "active_subscribers": 1234,
            "season_hit_rate_pct": 64.0,
            "races_scored": 7,
            "scored_picks": 28,
        }
    )
    assert "1,234" in html
    assert "on WhatsApp" in html
    assert ">Early<" not in html


def test_homepage_threshold_env_override() -> None:
    """Operator can lower the reveal threshold when they want the count
    to display earlier — e.g. internal demo, BD pitch deck."""
    os.environ["PITWALL_SUBSCRIBER_REVEAL_THRESHOLD"] = "5"
    try:
        html = render_homepage_html(
            {
                "active_subscribers": 23,
                "season_hit_rate_pct": 64.0,
                "races_scored": 7,
                "scored_picks": 28,
            }
        )
        # With threshold lowered to 5, the raw 23 is now revealed.
        assert ">23<" in html
        assert ">Early<" not in html
    finally:
        del os.environ["PITWALL_SUBSCRIBER_REVEAL_THRESHOLD"]


# ── Onboarding metrics + threshold ────────────────────────────────────────


def test_onboarding_threshold_clamps_to_unit_range() -> None:
    """Bad env input must not produce a nonsensical threshold."""
    from intelligence.onboarding_metrics import _threshold

    os.environ["PITWALL_ONBOARDING_THRESHOLD"] = "1.5"
    try:
        assert _threshold() == 1.0
    finally:
        del os.environ["PITWALL_ONBOARDING_THRESHOLD"]

    os.environ["PITWALL_ONBOARDING_THRESHOLD"] = "-0.5"
    try:
        assert _threshold() == 0.0
    finally:
        del os.environ["PITWALL_ONBOARDING_THRESHOLD"]

    os.environ["PITWALL_ONBOARDING_THRESHOLD"] = "garbage"
    try:
        assert _threshold() == 0.50  # falls back to default
    finally:
        del os.environ["PITWALL_ONBOARDING_THRESHOLD"]


@pytest.mark.asyncio
async def test_onboarding_alert_fires_when_below_threshold() -> None:
    """`check_and_alert` must call .warning when completion < threshold
    and the sample is large enough to trust."""
    from intelligence.onboarding_metrics import (
        OnboardingFunnel,
        check_and_alert_onboarding_funnel,
    )

    fake_funnel = OnboardingFunnel(
        active_subscribers=100,
        team_set=40,
        first_picks_received=30,
        completion_rate=0.30,
        below_threshold=True,
        threshold=0.50,
        min_sample_size=10,
    )
    with (
        patch(
            "intelligence.onboarding_metrics.compute_onboarding_funnel",
            new=AsyncMock(return_value=fake_funnel),
        ),
        patch("intelligence.onboarding_metrics.logger") as mock_logger,
    ):
        result = await check_and_alert_onboarding_funnel()
    assert result == fake_funnel
    mock_logger.bind.assert_called_once()
    mock_logger.bind.return_value.warning.assert_called_once()


@pytest.mark.asyncio
async def test_onboarding_alert_silent_when_sample_too_small() -> None:
    """A tiny cohort can't trigger an alert — that would page on noise
    in the first hour after launch when only a few users have signed up."""
    from intelligence.onboarding_metrics import (
        OnboardingFunnel,
        check_and_alert_onboarding_funnel,
    )

    small_funnel = OnboardingFunnel(
        active_subscribers=3,
        team_set=1,
        first_picks_received=0,
        completion_rate=0.0,
        below_threshold=False,  # sample under min_sample_size
        threshold=0.50,
        min_sample_size=10,
    )
    with (
        patch(
            "intelligence.onboarding_metrics.compute_onboarding_funnel",
            new=AsyncMock(return_value=small_funnel),
        ),
        patch("intelligence.onboarding_metrics.logger") as mock_logger,
    ):
        await check_and_alert_onboarding_funnel()
    mock_logger.bind.assert_not_called()


# ── Cost cut: vision budget defaults ──────────────────────────────────────


def test_vision_budget_defaults_tightened_for_bet1_volume() -> None:
    """Defaults must match realistic Bet-1 onboarding volume (1-2/user)."""
    # Ensure env doesn't shadow the test.
    for k in (
        "PITWALL_VISION_MAX_PER_PHONE_HOUR",
        "PITWALL_VISION_MAX_GLOBAL_DAY",
    ):
        os.environ.pop(k, None)

    from importlib import reload

    import intelligence.vision_budget as vb

    reload(vb)
    assert vb._phone_hourly_limit() == 2
    assert vb._global_daily_limit() == 500
