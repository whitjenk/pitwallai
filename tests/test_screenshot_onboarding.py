"""Tests for screenshot-based team onboarding (Bet 1 activation reducer)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from intelligence.team_extractor import (
    ExtractedTeam,
    ExtractionResult,
    extract_team_from_image,
)
from whatsapp.payload import extract_image_messages
from whatsapp.timezone_infer import infer_timezone


# ── 1. Timezone inference ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "phone,expected",
    [
        ("+447700900001", "Europe/London"),
        ("+12125551234", "America/New_York"),
        ("+61412345678", "Australia/Sydney"),
        ("+49301234567", "Europe/Berlin"),
        ("+919876543210", "Asia/Kolkata"),
        ("+971501234567", "Asia/Dubai"),
        ("+5511987654321", "America/Sao_Paulo"),
    ],
)
def test_infer_timezone_known_country_codes(phone: str, expected: str) -> None:
    assert infer_timezone(phone) == expected


def test_infer_timezone_unknown_falls_back() -> None:
    # +999 isn't a real country code.
    assert infer_timezone("+9991234567").startswith("Europe/")


def test_infer_timezone_empty_safe() -> None:
    assert infer_timezone("") == "Europe/London"


# ── 2. Image payload extraction ──────────────────────────────────────────────


def test_extract_image_messages_finds_image() -> None:
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "447700900001",
                        "id": "wamid.abc",
                        "type": "image",
                        "image": {
                            "id": "media-123",
                            "mime_type": "image/jpeg",
                            "caption": "my team",
                        },
                    }]
                }
            }]
        }]
    }
    images = extract_image_messages(payload)
    assert len(images) == 1
    assert images[0].media_id == "media-123"
    assert images[0].phone == "+447700900001"
    assert images[0].caption == "my team"


def test_extract_image_messages_skips_text() -> None:
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "447700900001",
                        "id": "wamid.abc",
                        "type": "text",
                        "text": {"body": "SUBSCRIBE"},
                    }]
                }
            }]
        }]
    }
    assert extract_image_messages(payload) == []


def test_extract_image_messages_skips_image_without_media_id() -> None:
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "447700900001",
                        "id": "wamid.abc",
                        "type": "image",
                        "image": {"mime_type": "image/jpeg"},
                    }]
                }
            }]
        }]
    }
    assert extract_image_messages(payload) == []


# ── 3. Extractor wrapper logic (vision call mocked) ─────────────────────────


@pytest.mark.asyncio
async def test_extract_team_rejects_non_team_screen() -> None:
    fake = ExtractedTeam(
        drivers=[], constructors=[],
        overall_confidence=0.9,
        not_a_team_screen=True,
    )

    class _FakeRun:
        output = fake

    fake_agent = AsyncMock()
    fake_agent.run = AsyncMock(return_value=_FakeRun())

    with patch("intelligence.team_extractor._build_agent", AsyncMock(return_value=fake_agent)):
        result = await extract_team_from_image(b"fake", mime_type="image/jpeg")

    assert result.status == "rejected"


@pytest.mark.asyncio
async def test_extract_team_full_success() -> None:
    fake = ExtractedTeam(
        drivers=["NOR", "VER", "LEC", "ALB", "HAM"],
        constructors=["MCL", "FER"],
        remaining_budget_m=4.2,
        transfers_available=2,
        overall_confidence=0.92,
        field_confidence={"budget": 0.9, "transfers": 0.85},
    )

    class _FakeRun:
        output = fake

    fake_agent = AsyncMock()
    fake_agent.run = AsyncMock(return_value=_FakeRun())

    with patch("intelligence.team_extractor._build_agent", AsyncMock(return_value=fake_agent)):
        result = await extract_team_from_image(b"fake", mime_type="image/jpeg")

    assert result.status == "ok"
    assert result.team is not None
    assert result.team.drivers == ["NOR", "VER", "LEC", "ALB", "HAM"]
    assert result.team.remaining_budget_m == 4.2
    assert result.missing_fields == []


@pytest.mark.asyncio
async def test_extract_team_partial_flags_missing() -> None:
    fake = ExtractedTeam(
        drivers=["NOR", "VER", "LEC"],  # only 3
        constructors=["MCL", "FER"],
        remaining_budget_m=None,
        transfers_available=None,
        overall_confidence=0.7,
    )

    class _FakeRun:
        output = fake

    fake_agent = AsyncMock()
    fake_agent.run = AsyncMock(return_value=_FakeRun())

    with patch("intelligence.team_extractor._build_agent", AsyncMock(return_value=fake_agent)):
        result = await extract_team_from_image(b"fake", mime_type="image/jpeg")

    assert result.status == "partial"
    assert "drivers" in result.missing_fields
    assert "budget" in result.missing_fields
    assert "transfers" in result.missing_fields


@pytest.mark.asyncio
async def test_extract_team_empty_image() -> None:
    result = await extract_team_from_image(b"", mime_type="image/jpeg")
    assert result.status == "error"


@pytest.mark.asyncio
async def test_extract_team_drops_unknown_driver_codes() -> None:
    fake = ExtractedTeam(
        drivers=["NOR", "XXX", "LEC", "ALB", "HAM"],  # XXX is bogus
        constructors=["MCL", "FER"],
        remaining_budget_m=4.2,
        transfers_available=2,
        overall_confidence=0.9,
    )

    class _FakeRun:
        output = fake

    fake_agent = AsyncMock()
    fake_agent.run = AsyncMock(return_value=_FakeRun())

    with patch("intelligence.team_extractor._build_agent", AsyncMock(return_value=fake_agent)):
        result = await extract_team_from_image(b"fake", mime_type="image/jpeg")

    assert result.team is not None
    assert "XXX" not in result.team.drivers
    # 4 valid + 0 invalid = partial because <5 drivers
    assert result.status == "partial"
    assert "drivers" in result.missing_fields
