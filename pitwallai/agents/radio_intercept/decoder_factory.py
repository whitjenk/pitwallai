"""Decoder factory and hybrid escalation policy."""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import replace
from typing import Protocol

from loguru import logger

from pitwallai.agents.radio_intercept.config import DecodeBackend, PitWallSettings
from pitwallai.agents.radio_intercept.llm_decoder import LLMDecoder
from pitwallai.agents.radio_intercept.models import AgentDependencies, DecodedTransmission, RadioRawMessage
from pitwallai.agents.radio_intercept.rules_decoder import RulesDecoder


class TransmissionDecoder(Protocol):
    """Protocol for radio transmission decoders."""

    async def decode(
        self,
        message: RadioRawMessage,
        deps: AgentDependencies,
    ) -> DecodedTransmission:
        """Decode a raw message into structured intelligence."""


class _DecodeCache:
    """TTL cache keyed by session + driver + normalized transcript hash."""

    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = ttl_seconds
        self._entries: dict[str, tuple[float, DecodedTransmission]] = {}

    def get(self, key: str) -> DecodedTransmission | None:
        """Return cached decode if not expired."""
        if self._ttl <= 0:
            return None
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() > expires_at:
            del self._entries[key]
            return None
        return value

    def put(self, key: str, value: DecodedTransmission) -> None:
        """Store decode result with TTL."""
        if self._ttl <= 0:
            return
        if len(self._entries) > 1024:
            self._evict_expired()
        self._entries[key] = (time.monotonic() + self._ttl, value)

    def _evict_expired(self) -> None:
        now = time.monotonic()
        expired = [key for key, (exp, _) in self._entries.items() if now > exp]
        for key in expired:
            del self._entries[key]


def _cache_key(message: RadioRawMessage) -> str:
    normalized = " ".join(message.raw_transcript.lower().split())
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"{message.session_key}:{message.driver_code}:{digest}"


class HybridDecoder:
    """
    Rules-first decoder with optional LLM escalation.

    Default path is local (no API spend). LLM runs only when configured and
    rules confidence is below the escalation threshold.
    """

    def __init__(self, settings: PitWallSettings) -> None:
        """
        Build hybrid decoder from settings.

        Args:
            settings: Application settings.

        Raises:
            ValueError: If LLM backend requested without model configured.
        """
        self._settings = settings
        self._rules = RulesDecoder()
        self._cache = _DecodeCache(settings.decode_dedup_ttl_seconds)
        self._llm: LLMDecoder | None = None

        if settings.decode_backend in (DecodeBackend.LLM, DecodeBackend.HYBRID):
            if not settings.llm_enabled:
                raise ValueError(
                    "PITWALL_LLM_MODEL must be set for decode backend "
                    f"'{settings.decode_backend.value}' (e.g. openai:gpt-4o-mini)"
                )
            semaphore = asyncio.Semaphore(settings.llm_max_concurrency)
            self._llm = LLMDecoder(settings.llm_model, semaphore=semaphore)

    async def decode(
        self,
        message: RadioRawMessage,
        deps: AgentDependencies,
    ) -> DecodedTransmission:
        """
        Decode with cache, rules path, and optional LLM escalation.

        Args:
            message: Raw radio message.
            deps: Shared dependencies.

        Returns:
            Decoded transmission.
        """
        key = _cache_key(message)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        backend = self._settings.decode_backend

        if backend == DecodeBackend.LLM:
            assert self._llm is not None
            result = await self._llm.decode(message, deps)
            self._cache.put(key, result)
            return result

        rules_result = await self._rules.decode(message, deps)

        should_escalate = (
            backend == DecodeBackend.HYBRID
            and self._llm is not None
            and rules_result.confidence_score < self._settings.llm_escalation_threshold
        )
        if should_escalate:
            logger.bind(
                driver=message.driver_code,
                confidence=rules_result.confidence_score,
            ).debug("Escalating low-confidence decode to LLM")
            result = await self._llm.decode(message, deps)
            self._cache.put(key, result)
            return result

        self._cache.put(key, rules_result)
        return rules_result


def create_decoder(
    settings: PitWallSettings | None = None,
    backend: str | None = None,
    llm_model: str | None = None,
) -> HybridDecoder:
    """
    Create the configured transmission decoder.

    Args:
        settings: Optional pre-built settings.
        backend: Optional backend override.
        llm_model: Optional LLM model override.

    Returns:
        HybridDecoder instance.
    """
    resolved = settings or PitWallSettings.from_env()
    if backend is not None:
        resolved = replace(
            resolved,
            decode_backend=DecodeBackend(backend),
            llm_model=llm_model or resolved.llm_model,
        )
    elif llm_model is not None:
        resolved = replace(resolved, llm_model=llm_model)
    return HybridDecoder(resolved)
