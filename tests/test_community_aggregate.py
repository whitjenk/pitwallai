"""Community aggregate broadcast tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from whatsapp.community_aggregate import (
    CommunityAggregateStats,
    broadcast_community_aggregate,
    format_community_aggregate_message,
)


def _stats(**overrides) -> CommunityAggregateStats:
    base = dict(
        race_name="Monaco Grand Prix",
        total_picks_sent=15,
        correct_picks_pct=67.0,
        personalized_count=10,
        generic_count=5,
        contrarian_avg_delta=4.5,
        consensus_avg_delta=2.0,
        contrarian_count=6,
        consensus_count=6,
        attack_mode_avg_gain=1.0,
        best_driver_code="NOR",
        season_races_scored=5,
        season_overall_accuracy=62.0,
        skip_ownership_comparison=False,
    )
    base.update(overrides)
    return CommunityAggregateStats(**base)


def test_message_under_char_limit() -> None:
    msg = format_community_aggregate_message(_stats())
    assert len(msg) <= 380
    assert "community results" in msg
    assert "pitwallai.app/accuracy" in msg


def test_message_omits_thin_contrarian_section() -> None:
    msg = format_community_aggregate_message(
        _stats(contrarian_avg_delta=None, consensus_avg_delta=2.0, contrarian_count=3)
    )
    assert "Contrarian picks" not in msg
    assert "Consensus picks led" not in msg


def test_first_race_skips_comparison() -> None:
    msg = format_community_aggregate_message(
        _stats(
            skip_ownership_comparison=True,
            contrarian_avg_delta=5.0,
            consensus_avg_delta=1.0,
        )
    )
    assert "Contrarian picks" not in msg
    assert "Consensus picks led" not in msg


@pytest.mark.asyncio
async def test_minimum_sample_gate() -> None:
    with (
        patch(
            "whatsapp.community_aggregate.load_community_aggregate_stats",
            new_callable=AsyncMock,
        ) as load_stats,
        patch(
            "whatsapp.community_aggregate.send_to_all_active",
            new_callable=AsyncMock,
        ) as send_all,
    ):
        load_stats.return_value = _stats(total_picks_sent=8)
        result = await broadcast_community_aggregate("2026_monaco")
        send_all.assert_not_called()
        assert result.get("skipped") == "insufficient_picks"


@pytest.mark.asyncio
async def test_broadcast_sends_when_sample_sufficient() -> None:
    with (
        patch(
            "whatsapp.community_aggregate.load_community_aggregate_stats",
            new_callable=AsyncMock,
        ) as load_stats,
        patch(
            "whatsapp.community_aggregate.send_to_all_active",
            new_callable=AsyncMock,
        ) as send_all,
    ):
        load_stats.return_value = _stats(total_picks_sent=15)
        send_all.return_value = {"sent": 3, "failed": 0}
        await broadcast_community_aggregate("2026_monaco")
        send_all.assert_called_once()
        message = send_all.call_args[0][0]
        assert len(message) <= 380
