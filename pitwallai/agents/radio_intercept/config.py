"""Runtime configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum


class DecodeBackend(str, Enum):
    """Decode execution strategy."""

    RULES = "rules"
    LLM = "llm"
    HYBRID = "hybrid"


def _parse_llm_provider_and_model(
    provider_raw: str,
    model_raw: str,
) -> tuple[str, str]:
    """
    Resolve provider and bare model name from env / legacy pydantic-ai strings.

    Supports legacy ``provider:model`` in PITWALL_LLM_MODEL (e.g. openai:gpt-4o-mini).

    Args:
        provider_raw: PITWALL_LLM_PROVIDER value.
        model_raw: PITWALL_LLM_MODEL value.

    Returns:
        Tuple of (provider, model_name).
    """
    model_raw = model_raw.strip()
    provider_raw = provider_raw.strip().lower() or "gemini"

    if ":" in model_raw:
        legacy_provider, _, legacy_model = model_raw.partition(":")
        legacy_provider = legacy_provider.strip().lower()
        legacy_model = legacy_model.strip()
        if legacy_provider in ("google-gla", "google-vertex", "google"):
            return "gemini", legacy_model or "gemini-2.0-flash"
        if legacy_provider == "anthropic":
            return "claude", legacy_model or "claude-3-5-sonnet-latest"
        if legacy_provider == "openai":
            return "openai", legacy_model or "gpt-4o-mini"
        return legacy_provider, legacy_model

    return provider_raw, model_raw or "gemini-2.0-flash"


@dataclass(frozen=True, slots=True)
class PitWallSettings:
    """
    Immutable application settings for decode pipeline and API.

    Attributes:
        decode_backend: Primary decode strategy (rules, llm, hybrid).
        llm_provider: LLM vendor (gemini, claude, openai, ollama).
        llm_model: Bare model name (e.g. gemini-2.0-flash).
        llm_use_vertex: Use Vertex AI for gemini (ADC); False uses Google AI Studio key.
        vertex_project: Google Cloud project id for Vertex AI.
        vertex_location: Google Cloud region for Vertex AI.
        llm_escalation_threshold: Hybrid mode escalates when rules confidence is below this.
        llm_max_concurrency: Maximum concurrent LLM requests.
        decode_dedup_ttl_seconds: TTL for identical-transcript decode cache.
        embedding_cache_size: LRU cache entries for transcript embeddings.
        bind_host: HTTP bind address.
        cors_origins: Allowed CORS origins (comma-separated in env).
        ws_max_connections: Maximum simultaneous dashboard WebSocket clients.
        log_transcripts: Whether to log full radio transcripts.
        llm_budget_acknowledged: Explicit opt-in for paid LLM usage.
        llm_max_calls_per_session: Hard cap on LLM calls per session_key.
        llm_max_calls_per_minute: Rolling per-minute LLM call cap.
        llm_max_calls_per_hour: Hourly LLM call cap.
        llm_max_calls_per_day: Daily LLM call cap.
        llm_max_estimated_usd_per_session: Estimated USD cap per session.
        llm_max_estimated_usd_per_day: Estimated USD cap per UTC day.
        llm_estimated_cost_per_call_usd: Conservative cost estimate per LLM call.
        llm_budget_cooldown_seconds: Cooldown after any cap breach.
        ollama_base_url: OpenAI-compatible Ollama base URL.
        explanation_cards_enabled: Include structured pick explanation cards in Saturday broadcasts.
    """

    decode_backend: DecodeBackend
    llm_provider: str
    llm_model: str
    llm_use_vertex: bool
    vertex_project: str
    vertex_location: str
    llm_escalation_threshold: float
    llm_max_concurrency: int
    decode_dedup_ttl_seconds: int
    embedding_cache_size: int
    bind_host: str
    cors_origins: tuple[str, ...]
    ws_max_connections: int
    log_transcripts: bool
    llm_budget_acknowledged: bool
    llm_max_calls_per_session: int
    llm_max_calls_per_minute: int
    llm_max_calls_per_hour: int
    llm_max_calls_per_day: int
    llm_max_estimated_usd_per_session: float
    llm_max_estimated_usd_per_day: float
    llm_estimated_cost_per_call_usd: float
    llm_budget_cooldown_seconds: int
    ollama_base_url: str
    explanation_cards_enabled: bool

    @classmethod
    def from_env(cls) -> PitWallSettings:
        """
        Load settings from environment variables with safe defaults.

        Returns:
            PitWallSettings instance.
        """
        backend_raw = os.getenv("PITWALL_DECODE_BACKEND", "rules").strip().lower()
        try:
            backend = DecodeBackend(backend_raw)
        except ValueError:
            backend = DecodeBackend.RULES

        llm_provider, llm_model = _parse_llm_provider_and_model(
            os.getenv("PITWALL_LLM_PROVIDER", "gemini"),
            os.getenv("PITWALL_LLM_MODEL", "gemini-2.0-flash"),
        )

        cors = os.getenv("PITWALL_CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000")
        origins = tuple(origin.strip() for origin in cors.split(",") if origin.strip())

        budget_ack = os.getenv("PITWALL_LLM_BUDGET_ACK", "").strip().lower() in (
            "1",
            "true",
            "yes",
            "i_accept",
        )

        use_vertex = os.getenv("PITWALL_LLM_USE_VERTEX", "true").strip().lower() in (
            "1",
            "true",
            "yes",
        )

        return cls(
            decode_backend=backend,
            llm_provider=llm_provider,
            llm_model=llm_model,
            llm_use_vertex=use_vertex,
            vertex_project=os.getenv("GOOGLE_CLOUD_PROJECT", "").strip(),
            vertex_location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1").strip(),
            llm_escalation_threshold=float(os.getenv("PITWALL_LLM_ESCALATION_THRESHOLD", "0.65")),
            llm_max_concurrency=max(1, int(os.getenv("PITWALL_LLM_MAX_CONCURRENCY", "2"))),
            decode_dedup_ttl_seconds=max(0, int(os.getenv("PITWALL_DECODE_DEDUP_TTL", "30"))),
            embedding_cache_size=max(64, int(os.getenv("PITWALL_EMBEDDING_CACHE_SIZE", "512"))),
            bind_host=os.getenv("PITWALL_BIND_HOST", "127.0.0.1"),
            cors_origins=origins,
            ws_max_connections=max(1, int(os.getenv("PITWALL_WS_MAX_CONNECTIONS", "32"))),
            log_transcripts=os.getenv("PITWALL_LOG_TRANSCRIPTS", "false").lower() == "true",
            llm_budget_acknowledged=budget_ack,
            llm_max_calls_per_session=max(0, int(os.getenv("PITWALL_LLM_MAX_CALLS_PER_SESSION", "12"))),
            llm_max_calls_per_minute=max(1, int(os.getenv("PITWALL_LLM_MAX_CALLS_PER_MINUTE", "4"))),
            llm_max_calls_per_hour=max(1, int(os.getenv("PITWALL_LLM_MAX_CALLS_PER_HOUR", "25"))),
            llm_max_calls_per_day=max(1, int(os.getenv("PITWALL_LLM_MAX_CALLS_PER_DAY", "75"))),
            llm_max_estimated_usd_per_session=float(
                os.getenv("PITWALL_LLM_MAX_USD_PER_SESSION", "0.50")
            ),
            llm_max_estimated_usd_per_day=float(os.getenv("PITWALL_LLM_MAX_USD_PER_DAY", "2.00")),
            llm_estimated_cost_per_call_usd=float(
                os.getenv("PITWALL_LLM_COST_PER_CALL_USD", "0.02")
            ),
            llm_budget_cooldown_seconds=max(
                0, int(os.getenv("PITWALL_LLM_BUDGET_COOLDOWN_SECONDS", "300"))
            ),
            ollama_base_url=os.getenv(
                "PITWALL_OLLAMA_BASE_URL", "http://localhost:11434/v1"
            ).strip(),
            explanation_cards_enabled=os.getenv(
                "EXPLANATION_CARDS_ENABLED", "false"
            ).strip().lower()
            in ("1", "true", "yes"),
        )

    @property
    def llm_enabled(self) -> bool:
        """Return True when LLM decode is configured (always has default model)."""
        return bool(self.llm_model)

    def llm_api_key(self) -> str:
        """Resolve BYOK API key for the configured provider."""
        from pitwallai.agents.radio_intercept.model_factory import resolve_api_key

        return resolve_api_key(self.llm_provider)
