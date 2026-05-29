"""Parse incoming Meta WhatsApp webhook payloads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class InboundMessage:
    """
    Normalized inbound WhatsApp text message.

    Attributes:
        phone: Sender phone in E.164 format.
        text: Message body (uppercased for command matching by caller).
        raw_text: Original message body.
        message_id: Meta message id for deduplication/logging.
    """

    phone: str
    text: str
    raw_text: str
    message_id: str


@dataclass(frozen=True, slots=True)
class InboundImage:
    """Normalized inbound WhatsApp image message (used for screenshot onboarding)."""

    phone: str
    media_id: str
    message_id: str
    mime_type: str
    caption: str = ""


def normalize_phone(raw: str) -> str:
    """
    Normalize a WhatsApp sender id to E.164.

    Args:
        raw: Phone from Meta (often digits only).

    Returns:
        E.164 string with leading +.
    """
    digits = raw.strip().lstrip("+")
    return f"+{digits}"


def extract_text_messages(payload: dict[str, Any]) -> list[InboundMessage]:
    """
    Extract inbound text messages from a Meta webhook JSON body.

    Args:
        payload: Parsed JSON POST body.

    Returns:
        List of inbound text messages (empty if none).
    """
    messages: list[InboundMessage] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for item in value.get("messages", []):
                if item.get("type") != "text":
                    continue
                text_body = (item.get("text") or {}).get("body", "")
                if not str(text_body).strip():
                    continue
                raw_phone = str(item.get("from", ""))
                messages.append(
                    InboundMessage(
                        phone=normalize_phone(raw_phone),
                        text=str(text_body).strip().upper(),
                        raw_text=str(text_body).strip(),
                        message_id=str(item.get("id", "")),
                    )
                )
    return messages


def extract_image_messages(payload: dict[str, Any]) -> list[InboundImage]:
    """Extract inbound image messages from a Meta webhook JSON body."""
    images: list[InboundImage] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for item in value.get("messages", []):
                if item.get("type") != "image":
                    continue
                image = item.get("image") or {}
                media_id = str(image.get("id", "")).strip()
                if not media_id:
                    continue
                images.append(
                    InboundImage(
                        phone=normalize_phone(str(item.get("from", ""))),
                        media_id=media_id,
                        message_id=str(item.get("id", "")),
                        mime_type=str(image.get("mime_type", "image/jpeg")),
                        caption=str(image.get("caption", "")).strip(),
                    )
                )
    return images
