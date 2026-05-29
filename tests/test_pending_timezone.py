"""DB-backed pending timezone state."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from whatsapp.timezone_infer import needs_manual_timezone


def test_needs_manual_timezone_unknown_country_code() -> None:
    assert needs_manual_timezone("+9991234567") is True


def test_needs_manual_timezone_uk_known() -> None:
    assert needs_manual_timezone("+447700900001") is False


@pytest.mark.asyncio
async def test_subscribe_sets_pending_for_unknown_cc() -> None:
    from contextlib import asynccontextmanager

    from whatsapp.subscribe_flow import handle_subscribe

    session = AsyncMock()
    session.get = AsyncMock(return_value=None)

    @asynccontextmanager
    async def _fake_session():
        yield session

    with (
        patch("whatsapp.subscribe_flow.get_session", _fake_session),
        patch(
            "whatsapp.subscribe_flow.set_pending_timezone",
            new=AsyncMock(),
        ) as mock_pending,
        patch(
            "whatsapp.subscribe_flow.screenshot_onboarding_enabled",
            return_value=False,
        ),
    ):
        messages = await handle_subscribe("+9991234567")

    mock_pending.assert_awaited_once_with("+9991234567")
    assert any("timezone" in m.lower() for m in messages)


@pytest.mark.asyncio
async def test_unsubscribe_mentions_delete() -> None:
    from contextlib import asynccontextmanager

    from whatsapp.subscribe_flow import handle_unsubscribe

    row = type("Sub", (), {"active": True})()
    session = AsyncMock()
    session.get = AsyncMock(return_value=row)

    @asynccontextmanager
    async def _fake_session():
        yield session

    with (
        patch("whatsapp.subscribe_flow.get_session", _fake_session),
        patch("whatsapp.subscribe_flow.clear_pending_timezone", new=AsyncMock()),
        patch("whatsapp.subscribe_flow.clear_pending_screenshot", new=AsyncMock()),
    ):
        reply = await handle_unsubscribe("+447700900001")

    assert "DELETE" in reply
