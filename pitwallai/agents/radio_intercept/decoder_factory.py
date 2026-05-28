"""Decoder factory and hybrid escalation policy."""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from dataclasses import replace
from typing import Protocol

from loguru import logger

from pitwallai.agents.radio_intercept.config import DecodeBackend, PitWallSettings
from pitwallai.agents.radio_intercept.llm_budget import LLMBudgetGuard
from pitwallai.agents.radio_intercept.llm_decoder import LLMDecoder
from pitwallai.agents.radio_intercept.models import AgentDependencies, DecodedTransmission, RadioRawMessage
from pitwallai.agents.radio_intercept.rules_decoder import RulesDecoder

# Phrases that turn evidence into strategist directives (forbidden in evidence_summary).
_DIRECTIVE_PHRASES: tuple[str, ...] = (
    "box now",
    "pit now",
    "you should",
    "you must",
    "we should",
    "recommend",
    "recommended",
    "immediately",
    "need to box",
    "need to pit",
    "must box",
    "must pit",
    "consider boxing",
    "consider pitting",
    "deploy now",
    "push now",
)

_IMPERATIVE_SENTENCE = re.compile(
    r"^\s*(box|pit|push|deploy|recommend|consider|must|should)\b",
    re.IGNORECASE,
)


def _sanitise_evidence_summary(text: str | None) -> str | None:
    """
    Strip directive language from LLM evidence summaries.

    The evidence_summary field must contain factual observations only — never
    instructions, recommendations, or action verbs directed at the strategist.

    Args:
        text: Raw LLM evidence summary.

    Returns:
        Sanitised summary, or None if nothing observational remains.
    """
    if text is None:
        return None
    cleaned = text.strip()
    if not cleaned:
        return None

    for phrase in _DIRECTIVE_PHRASES:
        cleaned = re.sub(re.escape(phrase), "", cleaned, flags=re.IGNORECASE)

    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,;.-")

    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    observational = [
        sentence.strip()
        for sentence in sentences
        if sentence.strip() and not _IMPERATIVE_SENTENCE.match(sentence.strip())
    ]
    result = " ".join(observational).strip()
    return result if result else None


def apply_llm_output_guards(transmission: DecodedTransmission) -> DecodedTransmission:
    """
    Apply post-LLM boundary guards before the result is cached or emitted.

    Args:
        transmission: LLM decode output after schema validation.

    Returns:
        Transmission with sanitised evidence_summary.
    """
    sanitised = _sanitise_evidence_summary(transmission.evidence_summary)
    if sanitised == transmission.evidence_summary:
        return transmission
    return transmission.model_copy(update={"evidence_summary": sanitised})


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
        effective = settings
        if settings.decode_backend in (DecodeBackend.LLM, DecodeBackend.HYBRID) and not settings.llm_model:
            if settings.decode_backend == DecodeBackend.LLM:
                raise ValueError(
                    "PITWALL_LLM_MODEL must be set for decode backend 'llm' "
                    "(default: gemini-2.0-flash via Vertex AI)"
                )
            logger.warning("Hybrid mode without LLM model — running rules-only")
            effective = replace(settings, decode_backend=DecodeBackend.RULES)

        if LLMBudgetGuard.blocks_llm_without_opt_in(effective):
            logger.error(
                "LLM/hybrid blocked: set PITWALL_LLM_BUDGET_ACK=1 after reviewing budget caps "
                "in .env.example (default rules-only is free)"
            )
            effective = replace(effective, decode_backend=DecodeBackend.RULES)

        self._settings = effective
        self._rules = RulesDecoder()
        self._cache = _DecodeCache(effective.decode_dedup_ttl_seconds)
        self._budget = LLMBudgetGuard(effective)
        self._llm: LLMDecoder | None = None

        if effective.decode_backend in (DecodeBackend.LLM, DecodeBackend.HYBRID) and effective.llm_enabled:
            semaphore = asyncio.Semaphore(effective.llm_max_concurrency)
            self._llm = LLMDecoder(
                effective,
                semaphore=semaphore,
                budget_guard=self._budget,
            )
            logger.bind(
                provider=effective.llm_provider,
                model=effective.llm_model,
                vertex=effective.llm_use_vertex,
                max_session_calls=effective.llm_max_calls_per_session,
                max_usd_session=effective.llm_max_estimated_usd_per_session,
                max_usd_day=effective.llm_max_estimated_usd_per_day,
            ).info("LLM enabled with budget guardrails active")

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

        rules_result = await self._rules.decode(message, deps)

        if backend == DecodeBackend.LLM:
            llm_result = await self._try_llm(message, deps, fallback=rules_result)
            self._cache.put(key, llm_result)
            return llm_result

        should_escalate = (
            backend == DecodeBackend.HYBRID
            and self._llm is not None
            and rules_result.confidence_score < self._settings.llm_escalation_threshold
        )
        if should_escalate:
            logger.bind(
                driver=message.driver_code,
                confidence=rules_result.confidence_score,
            ).debug("Considering LLM escalation for low-confidence decode")
            result = await self._try_llm(message, deps, fallback=rules_result)
            self._cache.put(key, result)
            return result

        self._cache.put(key, rules_result)
        return rules_result

    async def _try_llm(
        self,
        message: RadioRawMessage,
        deps: AgentDependencies,
        *,
        fallback: DecodedTransmission,
    ) -> DecodedTransmission:
        """
        Attempt LLM decode if budget allows; otherwise return rules fallback.

        Args:
            message: Raw radio message.
            deps: Shared dependencies.
            fallback: Rules decode to use when budget denies LLM.

        Returns:
            LLM decode or fallback.
        """
        if self._llm is None:
            return fallback

        budget = await self._budget.check(message.session_key)
        if not budget.allowed:
            logger.bind(
                driver=message.driver_code,
                session=message.session_key,
                reason=budget.deny_reason,
            ).info("LLM call blocked by budget guard — using rules decode")
            return fallback

        result = await self._llm.decode(message, deps)
        await self._budget.record(message.session_key)
        return apply_llm_output_guards(result)

    @property
    def budget_guard(self) -> LLMBudgetGuard:
        """Return the LLM budget guard for health/metrics endpoints."""
        return self._budget


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
