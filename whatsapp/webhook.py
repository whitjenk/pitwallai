"""Meta WhatsApp webhook routes."""

from __future__ import annotations

import json
import secrets
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Query, Request, Response, status
from loguru import logger

from intelligence.repository import (
    mark_inbound_message_processed,
    was_inbound_message_processed,
)
from whatsapp.inbound import handle_inbound_text
from whatsapp.payload import extract_text_messages
from whatsapp.settings import get_whatsapp_settings
from whatsapp.webhook_verify import (
    verify_meta_signature,
    webhook_skip_signature,
)

router = APIRouter(tags=["whatsapp"])


@router.get("/webhook")
async def webhook_verify(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
) -> Response:
    """
    Meta webhook verification handshake.

    Returns hub.challenge as plaintext when verify_token matches WEBHOOK_VERIFY_TOKEN.
    """
    settings = get_whatsapp_settings()
    expected = settings.webhook_verify_token
    if (
        hub_mode == "subscribe"
        and expected
        and secrets.compare_digest(hub_verify_token, expected)
    ):
        logger.info("WhatsApp webhook verified")
        return Response(content=hub_challenge, media_type="text/plain")
    logger.warning("WhatsApp webhook verification failed")
    return Response(status_code=status.HTTP_403_FORBIDDEN)


async def _process_payload(payload: dict[str, Any]) -> None:
    """
    Process inbound messages from a webhook payload asynchronously.

    Args:
        payload: Parsed JSON body from Meta.
    """
    for message in extract_text_messages(payload):
        if await was_inbound_message_processed(message.message_id):
            logger.debug("Skipping duplicate WhatsApp message_id={}", message.message_id)
            continue
        logger.debug(
            "Inbound WhatsApp message_id={} phone={}",
            message.message_id,
            message.phone[:6] + "…" if len(message.phone) > 6 else message.phone,
        )
        try:
            await handle_inbound_text(message.phone, message.text, message.raw_text)
        except Exception:
            logger.exception(
                "Inbound WhatsApp handler failed message_id={}",
                message.message_id,
            )
            raise
        await mark_inbound_message_processed(message.message_id)


@router.post("/webhook")
async def webhook_receive(
    request: Request,
    background_tasks: BackgroundTasks,
) -> Response:
    """
    Receive WhatsApp webhook events.

    Returns 200 immediately; message processing runs in a background task.
    """
    body = await request.body()
    settings = get_whatsapp_settings()
    mode = str(getattr(request.app.state, "mode", "unknown")).lower()
    signature_bypass = webhook_skip_signature() and mode != "live"
    if not signature_bypass:
        if not settings.whatsapp_app_secret.strip():
            logger.error("WHATSAPP_APP_SECRET not set — rejecting webhook POST")
            return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
        signature = request.headers.get("X-Hub-Signature-256")
        if not verify_meta_signature(body, signature, settings.whatsapp_app_secret):
            logger.warning("WhatsApp webhook signature verification failed")
            return Response(status_code=status.HTTP_403_FORBIDDEN)

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        logger.warning("WhatsApp webhook invalid JSON")
        return Response(status_code=status.HTTP_400_BAD_REQUEST)

    background_tasks.add_task(_process_payload, payload)
    return Response(status_code=status.HTTP_200_OK)
