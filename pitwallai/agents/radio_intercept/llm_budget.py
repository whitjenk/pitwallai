"""LLM spend guardrails — hard caps to prevent runaway API bills."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from pitwallai.agents.radio_intercept.config import DecodeBackend, PitWallSettings


@dataclass(frozen=True, slots=True)
class BudgetSnapshot:
    """
    Point-in-time LLM budget utilization.

    Attributes:
        allowed: Whether another LLM call is permitted right now.
        deny_reason: Human-readable reason when not allowed.
        session_calls: LLM calls this session_key.
        session_estimated_usd: Estimated spend this session_key.
        calls_last_minute: Rolling per-minute count.
        calls_last_hour: Calls in the current hour window.
        calls_today: Calls in the current UTC day window.
        estimated_usd_today: Estimated spend today.
        limits: Configured limit values for dashboards.
    """

    allowed: bool
    deny_reason: str | None
    session_calls: int
    session_estimated_usd: float
    calls_last_minute: int
    calls_last_hour: int
    calls_today: int
    estimated_usd_today: float
    limits: dict[str, float | int]
    llm_disabled_until: float | None = None


@dataclass
class _SessionSpend:
    """Per-session LLM usage counters."""

    calls: int = 0
    estimated_usd: float = 0.0
    warned_at_80_pct: bool = False


class LLMBudgetGuard:
    """
    Enforces hard limits on LLM API usage.

    All limits are checked before each call. When exhausted, callers must fall
    back to the rules decoder — never queue or retry LLM calls.
    """

    def __init__(self, settings: PitWallSettings) -> None:
        """
        Initialize the budget guard from settings.

        Args:
            settings: Application settings including budget caps.
        """
        self._settings = settings
        self._lock = asyncio.Lock()
        self._sessions: dict[int, _SessionSpend] = {}
        self._minute_timestamps: deque[float] = deque()
        self._hour_calls = 0
        self._hour_window_start = time.monotonic()
        self._day_calls = 0
        self._day_estimated_usd = 0.0
        self._day_window_start = time.time()
        self._llm_disabled_until: float | None = None
        self._total_calls = 0

    @staticmethod
    def is_opted_in(settings: PitWallSettings) -> bool:
        """
        Return True when the operator has explicitly acknowledged LLM spend risk.

        Args:
            settings: Application settings.

        Returns:
            True if PITWALL_LLM_BUDGET_ACK is set to a truthy value.
        """
        return settings.llm_budget_acknowledged

    @staticmethod
    def blocks_llm_without_opt_in(settings: PitWallSettings) -> bool:
        """
        Determine whether LLM usage should be blocked due to missing opt-in.

        Args:
            settings: Application settings.

        Returns:
            True when LLM/hybrid is configured but budget ack is missing.
        """
        if settings.decode_backend == DecodeBackend.RULES:
            return False
        return settings.llm_enabled and not settings.llm_budget_acknowledged

    async def check(self, session_key: int) -> BudgetSnapshot:
        """
        Check whether an LLM call is allowed without recording usage.

        Args:
            session_key: Active session identifier.

        Returns:
            BudgetSnapshot with allowed=False when any cap is exceeded.
        """
        async with self._lock:
            return self._check_locked(session_key)

    async def record(
        self,
        session_key: int,
        *,
        estimated_usd: float | None = None,
    ) -> BudgetSnapshot:
        """
        Record a completed LLM call and return updated budget state.

        Args:
            session_key: Active session identifier.
            estimated_usd: Override cost estimate; uses settings default if None.

        Returns:
            Post-call budget snapshot.
        """
        cost = (
            estimated_usd
            if estimated_usd is not None
            else self._settings.llm_estimated_cost_per_call_usd
        )
        async with self._lock:
            self._roll_windows_locked()
            now = time.monotonic()
            session = self._sessions.setdefault(session_key, _SessionSpend())
            session.calls += 1
            session.estimated_usd += cost
            self._minute_timestamps.append(now)
            self._hour_calls += 1
            self._day_calls += 1
            self._day_estimated_usd += cost
            self._total_calls += 1
            self._maybe_warn_locked(session_key, session)
            return self._check_locked(session_key)

    async def snapshot(self, session_key: int | None = None) -> BudgetSnapshot:
        """
        Return current budget utilization without mutating counters.

        Args:
            session_key: Optional session to include per-session stats.

        Returns:
            BudgetSnapshot for health endpoints and logging.
        """
        async with self._lock:
            self._roll_windows_locked()
            key = session_key if session_key is not None else 0
            return self._check_locked(key)

    def limits_dict(self) -> dict[str, float | int]:
        """Return configured limits for API responses."""
        s = self._settings
        return {
            "max_calls_per_session": s.llm_max_calls_per_session,
            "max_calls_per_minute": s.llm_max_calls_per_minute,
            "max_calls_per_hour": s.llm_max_calls_per_hour,
            "max_calls_per_day": s.llm_max_calls_per_day,
            "max_estimated_usd_per_session": s.llm_max_estimated_usd_per_session,
            "max_estimated_usd_per_day": s.llm_max_estimated_usd_per_day,
            "estimated_cost_per_call_usd": s.llm_estimated_cost_per_call_usd,
        }

    def _check_locked(self, session_key: int) -> BudgetSnapshot:
        self._roll_windows_locked()
        session = self._sessions.get(session_key, _SessionSpend())
        limits = self.limits_dict()
        now = time.monotonic()

        if self._llm_disabled_until is not None and now < self._llm_disabled_until:
            return self._snapshot_from(
                allowed=False,
                deny_reason="LLM temporarily disabled after budget breach (cooldown)",
                session=session,
                limits=limits,
            )

        if not self.is_opted_in(self._settings):
            return self._snapshot_from(
                allowed=False,
                deny_reason="Set PITWALL_LLM_BUDGET_ACK=1 to enable paid LLM decoding",
                session=session,
                limits=limits,
            )

        checks: list[tuple[str, bool]] = [
            (
                f"session call cap ({session.calls}/{self._settings.llm_max_calls_per_session})",
                session.calls < self._settings.llm_max_calls_per_session,
            ),
            (
                f"session spend cap (${session.estimated_usd:.2f}/${self._settings.llm_max_estimated_usd_per_session:.2f})",
                session.estimated_usd < self._settings.llm_max_estimated_usd_per_session,
            ),
            (
                f"per-minute cap ({len(self._minute_timestamps)}/{self._settings.llm_max_calls_per_minute})",
                len(self._minute_timestamps) < self._settings.llm_max_calls_per_minute,
            ),
            (
                f"hourly cap ({self._hour_calls}/{self._settings.llm_max_calls_per_hour})",
                self._hour_calls < self._settings.llm_max_calls_per_hour,
            ),
            (
                f"daily call cap ({self._day_calls}/{self._settings.llm_max_calls_per_day})",
                self._day_calls < self._settings.llm_max_calls_per_day,
            ),
            (
                f"daily spend cap (${self._day_estimated_usd:.2f}/${self._settings.llm_max_estimated_usd_per_day:.2f})",
                self._day_estimated_usd < self._settings.llm_max_estimated_usd_per_day,
            ),
        ]

        for reason, ok in checks:
            if not ok:
                self._trip_cooldown_locked()
                logger.bind(session=session_key, limit=reason).warning(
                    "LLM budget exceeded — falling back to rules decoder"
                )
                return self._snapshot_from(
                    allowed=False,
                    deny_reason=f"LLM budget exceeded: {reason}",
                    session=session,
                    limits=limits,
                )

        return self._snapshot_from(
            allowed=True,
            deny_reason=None,
            session=session,
            limits=limits,
        )

    def _snapshot_from(
        self,
        *,
        allowed: bool,
        deny_reason: str | None,
        session: _SessionSpend,
        limits: dict[str, float | int],
    ) -> BudgetSnapshot:
        return BudgetSnapshot(
            allowed=allowed,
            deny_reason=deny_reason,
            session_calls=session.calls,
            session_estimated_usd=round(session.estimated_usd, 4),
            calls_last_minute=len(self._minute_timestamps),
            calls_last_hour=self._hour_calls,
            calls_today=self._day_calls,
            estimated_usd_today=round(self._day_estimated_usd, 4),
            limits=limits,
            llm_disabled_until=self._llm_disabled_until,
        )

    def _roll_windows_locked(self) -> None:
        now_mono = time.monotonic()
        now_wall = time.time()

        while self._minute_timestamps and now_mono - self._minute_timestamps[0] >= 60.0:
            self._minute_timestamps.popleft()

        if now_mono - self._hour_window_start >= 3600.0:
            self._hour_calls = 0
            self._hour_window_start = now_mono

        if now_wall - self._day_window_start >= 86400.0:
            self._day_calls = 0
            self._day_estimated_usd = 0.0
            self._day_window_start = now_wall

    def _trip_cooldown_locked(self) -> None:
        """Pause all LLM calls for a short cooldown after hitting a cap."""
        cooldown = self._settings.llm_budget_cooldown_seconds
        if cooldown > 0:
            self._llm_disabled_until = time.monotonic() + cooldown

    def _maybe_warn_locked(self, session_key: int, session: _SessionSpend) -> None:
        if session.warned_at_80_pct:
            return
        session_limit = self._settings.llm_max_calls_per_session
        if session_limit <= 0:
            return
        if session.calls / session_limit >= 0.8:
            session.warned_at_80_pct = True
            logger.bind(
                session=session_key,
                calls=session.calls,
                limit=session_limit,
                estimated_usd=session.estimated_usd,
            ).warning("LLM budget at 80% of session call cap")

    def to_public_dict(self, snapshot: BudgetSnapshot) -> dict[str, Any]:
        """
        Serialize a snapshot for HTTP/WebSocket consumers.

        Args:
            snapshot: Budget snapshot.

        Returns:
            JSON-serializable dict.
        """
        return {
            "allowed": snapshot.allowed,
            "deny_reason": snapshot.deny_reason,
            "session_calls": snapshot.session_calls,
            "session_estimated_usd": snapshot.session_estimated_usd,
            "calls_last_minute": snapshot.calls_last_minute,
            "calls_last_hour": snapshot.calls_last_hour,
            "calls_today": snapshot.calls_today,
            "estimated_usd_today": snapshot.estimated_usd_today,
            "limits": snapshot.limits,
            "total_calls": self._total_calls,
        }
