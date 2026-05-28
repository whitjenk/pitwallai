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


@dataclass(frozen=True, slots=True)
class PitWallSettings:
    """
    Immutable application settings for decode pipeline and API.

    Attributes:
        decode_backend: Primary decode strategy (rules, llm, hybrid).
        llm_model: Pydantic AI model id (provider:model), empty disables LLM.
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
    """

    decode_backend: DecodeBackend
    llm_model: str
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

        cors = os.getenv("PITWALL_CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000")
        origins = tuple(origin.strip() for origin in cors.split(",") if origin.strip())

        budget_ack = os.getenv("PITWALL_LLM_BUDGET_ACK", "").strip().lower() in (
            "1",
            "true",
            "yes",
            "i_accept",
        )

        return cls(
            decode_backend=backend,
            llm_model=os.getenv("PITWALL_LLM_MODEL", "").strip(),
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
        )

    @property
    def llm_enabled(self) -> bool:
        """Return True when an LLM model id is configured."""
        return bool(self.llm_model)
