"""WhatsApp and database settings loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class WhatsAppSettings(BaseSettings):
    """
    Environment-backed settings for WhatsApp Cloud API and subscriber storage.

    No secrets are hardcoded — all values come from the environment or .env file.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""
    webhook_verify_token: str = ""
    whatsapp_app_secret: str = ""
    encryption_key: str = ""
    database_url: str = ""
    # WHATSAPP_DISPLAY_NUMBER — shown in /results CTA + SHARE attribution
    display_number: str = Field(default="", alias="WHATSAPP_DISPLAY_NUMBER")

    def whatsapp_configured(self) -> bool:
        """Return True when Meta Cloud API credentials are present."""
        return bool(self.whatsapp_token.strip() and self.whatsapp_phone_number_id.strip())


@lru_cache
def get_whatsapp_settings() -> WhatsAppSettings:
    """
    Return cached WhatsApp settings singleton.

    Returns:
        WhatsAppSettings loaded from the environment.
    """
    return WhatsAppSettings()


def _digits_only(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def wa_me_link(prefill: str = "SUBSCRIBE") -> str:
    """
    Build a click-to-chat WhatsApp deep link.

    Tap → opens WhatsApp directly to the PitWallAI thread with ``prefill``
    already typed. Recipient just taps send. Returns empty string when
    WHATSAPP_DISPLAY_NUMBER is unset (caller should fall back to the
    static landing page).
    """
    from urllib.parse import quote

    number = _digits_only(get_whatsapp_settings().display_number)
    if not number:
        return ""
    return f"https://wa.me/{number}?text={quote(prefill)}"
