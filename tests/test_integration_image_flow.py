"""Webhook → image download → vision extract → save → reply (mocked externals)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from intelligence.team_extractor import ExtractedTeam, ExtractionResult
from whatsapp.webhook import _process_payload

_PHONE = "+447700900001"
_MESSAGE_ID = "wamid.integration.image.1"
_MEDIA_ID = "media-integration-1"

_IMAGE_WEBHOOK = {
    "entry": [{
        "changes": [{
            "value": {
                "messages": [{
                    "from": "447700900001",
                    "id": _MESSAGE_ID,
                    "type": "image",
                    "image": {
                        "id": _MEDIA_ID,
                        "mime_type": "image/jpeg",
                    },
                }]
            }
        }]
    }]
}

_FAKE_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16

_FAKE_TEAM = ExtractedTeam(
    drivers=["NOR", "VER", "LEC", "ALB", "HAM"],
    constructors=["MCL", "FER"],
    remaining_budget_m=4.2,
    transfers_available=2,
    overall_confidence=0.95,
    field_confidence={"budget": 0.9, "transfers": 0.85},
)


@pytest.mark.asyncio
async def test_webhook_image_flow_saves_team_and_replies() -> None:
    sent: list[str] = []

    async def _capture_send(phone: str, message: str) -> None:
        sent.append(message)

    with (
        patch(
            "whatsapp.webhook.claim_inbound_message",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "whatsapp.webhook.complete_inbound_message",
            new=AsyncMock(),
        ),
        patch(
            "whatsapp.inbound_image.get_pending_screenshot",
            new=AsyncMock(return_value="team_setup"),
        ),
        patch(
            "whatsapp.inbound_image.check_vision_budget",
            new=AsyncMock(return_value=type("R", (), {"allowed": True, "reason": ""})()),
        ),
        patch(
            "whatsapp.inbound_image.download_media",
            new=AsyncMock(return_value=(_FAKE_JPEG, "image/jpeg")),
        ),
        patch(
            "whatsapp.inbound_image.record_vision_call_for",
            new=AsyncMock(),
        ),
        patch(
            "whatsapp.inbound_image.extract_team_from_image",
            new=AsyncMock(
                return_value=ExtractionResult(status="ok", team=_FAKE_TEAM),
            ),
        ),
        patch(
            "whatsapp.inbound_image.upsert_fantasy_team_fields",
            new=AsyncMock(),
        ) as mock_upsert,
        patch(
            "whatsapp.inbound_image.clear_pending_screenshot",
            new=AsyncMock(),
        ),
        patch(
            "whatsapp.inbound_image.send_message",
            side_effect=_capture_send,
        ),
    ):
        await _process_payload(_IMAGE_WEBHOOK)

    mock_upsert.assert_awaited_once()
    assert mock_upsert.await_args.args[0] == _PHONE
    assert any("Got your team" in msg for msg in sent)
    assert any("NOR" in msg for msg in sent)


@pytest.mark.asyncio
async def test_webhook_image_skipped_when_not_claimed() -> None:
    with (
        patch(
            "whatsapp.webhook.claim_inbound_message",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "whatsapp.inbound_image.handle_inbound_image",
            new=AsyncMock(),
        ) as mock_handle,
    ):
        await _process_payload(_IMAGE_WEBHOOK)

    mock_handle.assert_not_awaited()
