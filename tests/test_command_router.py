"""WhatsApp inbound command router tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from whatsapp.command_router import route


@pytest.mark.asyncio
async def test_help_command() -> None:
    reply = await route("help", "+15550001111", "2026_monaco")
    assert "PitWallAI Commands" in reply
    assert "PICKS" in reply


@pytest.mark.asyncio
async def test_unknown_input_returns_help() -> None:
    reply = await route("xyzzy nonsense", "+15550001111", "2026_monaco")
    assert "PitWallAI Commands" in reply


@pytest.mark.asyncio
async def test_driver_code_routing() -> None:
    with patch(
        "whatsapp.commands.driver.handle_driver",
        new=AsyncMock(return_value="NOR brief"),
    ) as mock_driver:
        reply = await route("nor", "+15550001111", "2026_monaco")
    mock_driver.assert_awaited_once_with(
        driver_code="NOR",
        phone_number="+15550001111",
        race_key="2026_monaco",
    )
    assert reply == "NOR brief"


@pytest.mark.asyncio
async def test_unknown_four_letter_code_returns_help() -> None:
    """Codes not on the 2026 grid fall through to HELP (not an error)."""
    reply = await route("ZZZZ", "+15550001111", "2026_monaco")
    assert "PitWallAI Commands" in reply


@pytest.mark.asyncio
async def test_valid_driver_without_data() -> None:
    with patch(
        "whatsapp.commands.driver.handle_driver",
        new=AsyncMock(return_value="No pick data for *BOT* this weekend."),
    ):
        reply = await route("BOT", "+15550001111", "2026_monaco")
    assert "No pick data" in reply


@pytest.mark.asyncio
async def test_handler_exception_returns_error_reply() -> None:
    async def _boom(**_kwargs):
        raise RuntimeError("boom")

    with patch("whatsapp.commands.registry.get", return_value=_boom):
        reply = await route("streak", "+15550001111", "2026_monaco")
    assert "Something went wrong" in reply
    assert "HELP" in reply


@pytest.mark.asyncio
async def test_streak_with_mocked_data() -> None:
    from contextlib import asynccontextmanager

    class _Row:
        overall_accuracy = 72.0
        best_circuit = "monaco"
        worst_circuit = "spa"

    class _Session:
        async def scalar(self, _stmt):
            return 5

    @asynccontextmanager
    async def _fake_session():
        yield _Session()

    with (
        patch(
            "whatsapp.commands.streak.load_season_accuracy_row",
            new=AsyncMock(return_value=_Row()),
        ),
        patch("whatsapp.commands.streak.get_session", _fake_session),
    ):
        reply = await route("STREAK", "+15550001111", "2026_monaco")

    assert "Hit Rate" in reply
    assert "72" in reply
