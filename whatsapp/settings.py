"""WhatsApp and database settings loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache

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
    encryption_key: str = ""
    database_url: str = ""

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
