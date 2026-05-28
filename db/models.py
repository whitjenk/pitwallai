"""SQLAlchemy models for PitWallAI."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class Subscriber(Base):
    """
    WhatsApp subscriber with optional BYOK LLM credentials.

    Attributes:
        phone: E.164 phone number (primary key).
        timezone: IANA timezone name for race alerts.
        preferred_provider: LLM provider id (gemini, claude, openai, ollama).
        encrypted_api_key: Fernet-encrypted user API key, if set.
        active: Soft-delete flag; inactive subscribers receive no broadcasts.
        created_at: UTC timestamp when the row was created.
    """

    __tablename__ = "subscribers"

    phone: Mapped[str] = mapped_column(String(20), primary_key=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    preferred_provider: Mapped[str] = mapped_column(String(32), nullable=False, default="gemini")
    encrypted_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
