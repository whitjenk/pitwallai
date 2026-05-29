"""Tests for the Tier 1 UX polish: HELP refresh, UPDATE command, calibration block."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from intelligence.eval.calibration import BandReport, ConfidenceBand
from scripts.generate_results_page import calibration_body
from whatsapp.commands.help import handle_help
from whatsapp.commands.update import handle_update


# ── HELP refresh ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_help_lists_current_bet1_commands() -> None:
    out = await handle_help(phone_number="+1", race_key="2026_monaco")
    for cmd in ("PICKS", "TEAM", "SHARE", "UPDATE", "HISTORY", "STREAK"):
        assert cmd in out, f"HELP missing {cmd}"


@pytest.mark.asyncio
async def test_help_does_not_advertise_flagged_off_commands() -> None:
    out = await handle_help(phone_number="+1", race_key="2026_monaco")
    # All four off-bet flags default OFF in tests.
    assert "CHIPS" not in out
    assert "TRANSFERS" not in out
    assert "BUDGET" not in out
    assert "WHY CONSTRUCTOR" not in out


@pytest.mark.asyncio
async def test_help_mentions_screenshot_path() -> None:
    out = await handle_help(phone_number="+1", race_key="2026_monaco")
    assert "screenshot" in out.lower()


# ── UPDATE command ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_rejects_malformed_input() -> None:
    out = await handle_update("+1", "UPDATE D4")
    assert "Use:" in out


@pytest.mark.asyncio
async def test_update_rejects_unknown_driver() -> None:
    out = await handle_update("+1", "UPDATE D4 XXX")
    assert "Unknown driver" in out


@pytest.mark.asyncio
async def test_update_writes_single_driver_slot() -> None:
    with patch(
        "whatsapp.commands.update.upsert_fantasy_team_fields",
        new=AsyncMock(),
    ) as upsert:
        out = await handle_update("+1", "UPDATE D4 ALB")
    assert "ALB" in out
    upsert.assert_awaited_once()
    assert upsert.call_args.kwargs == {"driver_4": "ALB"}


@pytest.mark.asyncio
async def test_update_writes_constructor_slot() -> None:
    with patch(
        "whatsapp.commands.update.upsert_fantasy_team_fields",
        new=AsyncMock(),
    ) as upsert:
        out = await handle_update("+1", "UPDATE C2 MCL")
    assert "MCL" in out
    upsert.assert_awaited_once()
    assert upsert.call_args.kwargs == {"constructor_2": "MCL"}


@pytest.mark.asyncio
async def test_update_writes_budget() -> None:
    with patch(
        "whatsapp.commands.update.upsert_fantasy_team_fields",
        new=AsyncMock(),
    ) as upsert:
        out = await handle_update("+1", "UPDATE BUDGET 4.2")
    assert "$4.2M" in out
    upsert.assert_awaited_once()
    assert upsert.call_args.kwargs == {"remaining_budget": 4.2}


@pytest.mark.asyncio
async def test_update_rejects_out_of_range_transfers() -> None:
    out = await handle_update("+1", "UPDATE TRANSFERS 99")
    assert "between" in out


# ── /results calibration block ───────────────────────────────────────────────


def test_calibration_body_empty_when_no_data() -> None:
    assert calibration_body(None) == ""
    assert calibration_body([]) == ""


def test_calibration_body_renders_well_calibrated_band() -> None:
    reports = [BandReport(
        band=ConfidenceBand.HIGH,
        sample_size=20,
        hit_rate=0.70,
        target_hit_rate=0.70,
    )]
    out = calibration_body(reports)
    assert "HIGH" in out
    assert "70%" in out
    assert "calibrated" in out


def test_calibration_body_flags_drift_negative() -> None:
    reports = [BandReport(
        band=ConfidenceBand.HIGH,
        sample_size=20,
        hit_rate=0.50,
        target_hit_rate=0.70,
    )]
    out = calibration_body(reports)
    # Negative drift gets a -pp badge
    assert "-20pp" in out or "-20" in out
    assert "drift-down" in out


def test_calibration_body_skips_zero_sample_bands() -> None:
    reports = [
        BandReport(band=ConfidenceBand.HIGH, sample_size=20, hit_rate=0.7, target_hit_rate=0.7),
        BandReport(band=ConfidenceBand.MED, sample_size=0, hit_rate=0.0, target_hit_rate=0.55),
    ]
    out = calibration_body(reports)
    # MED with sample_size=0 should not appear as a row
    assert ">MED<" not in out
