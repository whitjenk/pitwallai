"""Closed-beta launch gates: config, prices, subscribe capacity."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from db.models import FantasyTeam
from fantasy.price_catalog import load_price_catalog, prices_trusted
from intelligence.context import init_orchestrator_context
from intelligence.pick_generator import generate_picks
from intelligence.schemas import PickGeneratorInput, QualifyingRow
from intelligence.spend_guard import SpendGuardSnapshot, SpendMode
from pitwallai.launch_validate import validate_launch_config
from whatsapp import subscribe_flow as sub_mod


@pytest.fixture(autouse=True)
def _reload_price_catalog() -> None:
    load_price_catalog()


def test_live_launch_requires_whatsapp_creds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("WHATSAPP_TOKEN", raising=False)
    monkeypatch.delenv("WHATSAPP_PHONE_NUMBER_ID", raising=False)
    monkeypatch.delenv("WEBHOOK_VERIFY_TOKEN", raising=False)
    monkeypatch.delenv("WHATSAPP_APP_SECRET", raising=False)
    monkeypatch.delenv("WHATSAPP_DISPLAY_NUMBER", raising=False)
    monkeypatch.delenv("PITWALL_DEV_ONLY_SKIP_WEBHOOK_SIGNATURE", raising=False)
    from whatsapp.settings import get_whatsapp_settings

    get_whatsapp_settings.cache_clear()

    check = validate_launch_config(mode="live")
    assert not check.ok
    assert any("DATABASE_URL" in e for e in check.errors)
    assert any("WHATSAPP_TOKEN" in e for e in check.errors)
    assert any("PITWALL_PRICES_VERIFIED" in w for w in check.warnings)


def test_live_launch_ok_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
    monkeypatch.setenv("WHATSAPP_TOKEN", "token")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "123")
    monkeypatch.setenv("WEBHOOK_VERIFY_TOKEN", "verify")
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "secret")
    monkeypatch.setenv("WHATSAPP_DISPLAY_NUMBER", "+15551234567")
    monkeypatch.setenv("PITWALL_PRICES_VERIFIED", "1")
    monkeypatch.delenv("PITWALL_DEV_ONLY_SKIP_WEBHOOK_SIGNATURE", raising=False)
    from whatsapp.settings import get_whatsapp_settings

    get_whatsapp_settings.cache_clear()

    check = validate_launch_config(mode="live")
    assert check.ok
    assert not check.errors


def test_assert_live_ready_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from pitwallai.launch_validate import assert_live_ready
    from whatsapp.settings import get_whatsapp_settings

    monkeypatch.delenv("WHATSAPP_TOKEN", raising=False)
    get_whatsapp_settings.cache_clear()
    with pytest.raises(RuntimeError, match="Live launch configuration invalid"):
        assert_live_ready(mode="live")


def test_transfer_picks_gated_without_verified_prices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PITWALL_PRICES_VERIFIED", raising=False)
    assert not prices_trusted()

    ctx = init_orchestrator_context()
    monaco = ctx.get_circuit("monaco")
    assert monaco is not None
    team = FantasyTeam(
        phone="+15550000001",
        driver_1="VER",
        driver_2="NOR",
        driver_3="LEC",
        driver_4="ALB",
        driver_5="HAM",
        remaining_budget=25.0,
        transfers_available=2,
        chips_used={},
    )
    output = generate_picks(
        PickGeneratorInput(
            circuit=monaco,
            practice_signals=[],
            qualifying_result=[
                QualifyingRow(driver_number=1, driver_code="LEC", grid_position=1, session_key=1),
                QualifyingRow(driver_number=2, driver_code="VER", grid_position=2, session_key=1),
                QualifyingRow(driver_number=3, driver_code="NOR", grid_position=3, session_key=1),
                QualifyingRow(driver_number=4, driver_code="HAM", grid_position=5, session_key=1),
                QualifyingRow(driver_number=5, driver_code="ALB", grid_position=10, session_key=1),
                QualifyingRow(driver_number=6, driver_code="COL", grid_position=8, session_key=1),
            ],
            weather_forecast=None,
            user_team=team,
            race_key="2026_monaco",
            generated_by="rules",
        )
    )
    assert not output.personalized
    assert "paused until prices are verified" in (output.confidence_note or "")


def test_transfer_picks_enabled_when_prices_verified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PITWALL_PRICES_VERIFIED", "1")
    assert prices_trusted()

    ctx = init_orchestrator_context()
    monaco = ctx.get_circuit("monaco")
    assert monaco is not None
    team = FantasyTeam(
        phone="+15550000001",
        driver_1="VER",
        driver_2="NOR",
        driver_3="LEC",
        driver_4="ALB",
        driver_5="HAM",
        remaining_budget=25.0,
        transfers_available=2,
        chips_used={},
    )
    output = generate_picks(
        PickGeneratorInput(
            circuit=monaco,
            practice_signals=[],
            qualifying_result=[
                QualifyingRow(driver_number=1, driver_code="LEC", grid_position=1, session_key=1),
                QualifyingRow(driver_number=2, driver_code="VER", grid_position=2, session_key=1),
                QualifyingRow(driver_number=3, driver_code="NOR", grid_position=3, session_key=1),
                QualifyingRow(driver_number=4, driver_code="HAM", grid_position=5, session_key=1),
                QualifyingRow(driver_number=5, driver_code="ALB", grid_position=10, session_key=1),
                QualifyingRow(driver_number=6, driver_code="COL", grid_position=8, session_key=1),
            ],
            weather_forecast=None,
            user_team=team,
            race_key="2026_monaco",
            generated_by="rules",
        )
    )
    assert output.personalized


@pytest.mark.asyncio
async def test_subscribe_blocked_when_signups_paused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paused = SpendGuardSnapshot(
        month_key="2026-05",
        monthly_spent_usd=100.0,
        monthly_cap_usd=75.0,
        mode=SpendMode.DEGRADED,
        llm_allowed=False,
        vision_allowed=False,
        signups_allowed=False,
        pct_of_cap=133.3,
    )
    with patch(
        "intelligence.spend_guard.get_spend_guard",
        new=AsyncMock(return_value=paused),
    ):
        msgs = await sub_mod.handle_subscribe("+15551234567")
    assert len(msgs) == 1
    assert "capacity" in msgs[0].lower()


def test_beta_disclaimer_under_160_chars() -> None:
    assert len(sub_mod._BETA_DISCLAIMER) <= 160
    assert "Beta" in sub_mod._BETA_DISCLAIMER
