"""Outbound WhatsApp messages via Meta Cloud API."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
from loguru import logger

from whatsapp.settings import get_whatsapp_settings

_GRAPH_API_VERSION = "v18.0"
_MAX_RETRIES = 3
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# Meta error codes meaning the recipient is outside the 24h customer-service
# window, so a free-form (non-template) message is rejected.
#   131047 — "Re-engagement message": >24h since the user last messaged.
#   470    — legacy re-engagement / outside-window code.
_WINDOW_ERROR_CODES = {131047, 470}


class WhatsAppWindowError(RuntimeError):
    """Send rejected because the recipient is outside the 24h session window.

    A proactive (business-initiated) free-form message can only be delivered
    within 24h of the user's last inbound message. Outside that window Meta
    requires a pre-approved template. Raised so broadcast loops can log this
    distinctly instead of treating it as a generic failure.
    """


def _meta_error_code(exc: httpx.HTTPStatusError) -> int | None:
    """Extract Meta's numeric error code from a failed response, if present."""
    try:
        return int(exc.response.json().get("error", {}).get("code"))
    except (ValueError, TypeError, AttributeError):
        return None


def mask_phone(phone: str) -> str:
    """
    Mask a phone number for logs (E.164).

    Args:
        phone: Full E.164 phone.

    Returns:
        Masked phone string.
    """
    if len(phone) <= 6:
        return "***"
    return f"{phone[:3]}***{phone[-3:]}"


async def send_message(phone: str, text: str) -> dict[str, Any]:
    """
    Send a WhatsApp text message via Meta Cloud API.

    Uses exponential backoff on HTTP 429 and 5xx (max 3 retries).

    Args:
        phone: Recipient E.164 phone number.
        text: Message body (keep under 160 chars for SMS-style UX).

    Returns:
        Parsed JSON response from Meta.

    Raises:
        ValueError: If WhatsApp credentials are not configured.
        httpx.HTTPStatusError: On non-retryable HTTP errors after retries exhausted.
    """
    settings = get_whatsapp_settings()
    if not settings.whatsapp_configured():
        raise ValueError("WHATSAPP_TOKEN and WHATSAPP_PHONE_NUMBER_ID must be configured")

    url = (
        f"https://graph.facebook.com/{_GRAPH_API_VERSION}/"
        f"{settings.whatsapp_phone_number_id.strip()}/messages"
    )
    recipient = phone.lstrip("+")
    body = {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "text",
        "text": {"body": text},
    }
    headers = {
        "Authorization": f"Bearer {settings.whatsapp_token.strip()}",
        "Content-Type": "application/json",
    }

    last_error: Exception | None = None
    started = time.perf_counter()

    async with httpx.AsyncClient(timeout=30.0) as client:
        for attempt in range(_MAX_RETRIES):
            try:
                response = await client.post(url, json=body, headers=headers)
                latency_ms = (time.perf_counter() - started) * 1000

                if response.status_code in _RETRYABLE_STATUS and attempt < _MAX_RETRIES - 1:
                    delay = 2.0**attempt
                    logger.warning(
                        "WhatsApp send retryable status={} attempt={} delay_s={} phone={}",
                        response.status_code,
                        attempt + 1,
                        delay,
                        mask_phone(phone),
                    )
                    await asyncio.sleep(delay)
                    continue

                response.raise_for_status()
                data = response.json()
                logger.info(
                    "WhatsApp send ok phone={} status={} latency_ms={:.0f}",
                    mask_phone(phone),
                    response.status_code,
                    latency_ms,
                )
                from intelligence.spend_guard import record_spend, whatsapp_cost_per_message_usd

                cost = whatsapp_cost_per_message_usd()
                if cost > 0:
                    await record_spend("whatsapp", cost)
                return data
            except httpx.HTTPStatusError as exc:
                last_error = exc
                status = exc.response.status_code
                if status in _RETRYABLE_STATUS and attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(2.0**attempt)
                    continue
                latency_ms = (time.perf_counter() - started) * 1000
                error_code = _meta_error_code(exc)
                if error_code in _WINDOW_ERROR_CODES:
                    logger.warning(
                        "WhatsApp send BLOCKED — outside 24h window phone={} code={}. "
                        "Proactive free-form messages need the recipient to have texted "
                        "the bot within 24h (or a pre-approved template). Message NOT "
                        "delivered.",
                        mask_phone(phone),
                        error_code,
                    )
                    raise WhatsAppWindowError(
                        f"recipient outside 24h window (Meta code {error_code})"
                    ) from exc
                logger.error(
                    "WhatsApp send failed phone={} status={} code={} latency_ms={:.0f}",
                    mask_phone(phone),
                    status,
                    error_code,
                    latency_ms,
                )
                raise
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(2.0**attempt)
                    continue
                logger.error(
                    "WhatsApp send error phone={} err={}",
                    mask_phone(phone),
                    exc,
                )
                raise

    if last_error:
        raise last_error
    raise RuntimeError("WhatsApp send failed without response")
