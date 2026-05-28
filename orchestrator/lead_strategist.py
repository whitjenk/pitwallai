"""Lead Strategist — coordinates agents and shared RaceContext."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from agents.base import (
    AGENT1_BUDGET_S,
    AGENT2_BUDGET_S,
    AGENT3_BUDGET_S,
    AGENT5_BUDGET_S,
    AgentRunDependencies,
    run_agent,
)
from agents.context_builder import run_context_builder
from agents.practice_analyst import run_practice_analyst
from agents.quali_strategist import run_quali_strategist
from agents.race_monitor import run_race_monitor
from agents.scorer_learner import run_scorer_and_learner
from circuits.profiles import get_circuit_profile
from openf1.client import OpenF1Client
from orchestrator.context_store import get_context, set_context
from orchestrator.race_context import initial_race_context, RaceContext
from scheduler.calendar import get_race_weekend, profile_circuit_key

if TYPE_CHECKING:
    from fastapi import FastAPI


class LeadStrategist:
    """
    Single coordinator for the race weekend agent pipeline.

    Holds no mutable state — reads/writes RaceContext via context_store.
    """

    def __init__(self, deps: AgentRunDependencies) -> None:
        self._deps = deps

    @classmethod
    def from_app(cls, deps: AgentRunDependencies) -> LeadStrategist:
        return cls(deps)

    @classmethod
    def from_fastapi(cls, app: FastAPI) -> LeadStrategist:
        """Build dependencies from FastAPI app.state."""
        return cls(
            AgentRunDependencies(
                openf1_client=OpenF1Client(),
                radio_agent=app.state.agent,
                vector_store=app.state.vector_store,
                settings=app.state.settings,
            )
        )

    def _bootstrap_context(self, race_key: str) -> RaceContext | None:
        existing = get_context(race_key)
        if existing is not None:
            return existing
        weekend = get_race_weekend(race_key)
        if weekend is None:
            logger.error("Unknown race_key={}", race_key)
            return None
        profile = get_circuit_profile(profile_circuit_key(weekend.circuit_key))
        if profile is None:
            logger.error("No profile for race_key={}", race_key)
            return None
        ctx = initial_race_context(weekend, profile)
        set_context(ctx)
        return ctx

    def _commit(self, ctx: RaceContext) -> None:
        set_context(ctx)

    async def run_context_builder(self, race_key: str) -> None:
        """Agent 1 — Thursday context build."""
        ctx = self._bootstrap_context(race_key)
        if ctx is None:
            return
        result = await run_agent(
            run_context_builder,
            ctx,
            self._deps,
            agent_name="Agent1-ContextBuilder",
            budget_s=AGENT1_BUDGET_S,
        )
        self._commit(result)

    async def run_practice_analyst(self, race_key: str) -> None:
        """Agent 2 — post-FP2 practice analysis."""
        ctx = self._bootstrap_context(race_key)
        if ctx is None:
            return
        result = await run_agent(
            run_practice_analyst,
            ctx,
            self._deps,
            agent_name="Agent2-PracticeAnalyst",
            budget_s=AGENT2_BUDGET_S,
        )
        self._commit(result)

    async def run_quali_strategist(self, race_key: str) -> None:
        """Agent 3 — Saturday quali picks broadcast."""
        ctx = self._bootstrap_context(race_key)
        if ctx is None:
            return
        result = await run_agent(
            run_quali_strategist,
            ctx,
            self._deps,
            agent_name="Agent3-QualiStrategist",
            budget_s=AGENT3_BUDGET_S,
        )
        self._commit(result)

    async def run_race_monitor(self, race_key: str) -> None:
        """Agent 4 — start live race monitor (long-lived)."""
        ctx = self._bootstrap_context(race_key)
        if ctx is None:
            return
        # Load signal quality for downstream weighting
        from intelligence.repository import build_signal_quality_from_db

        sq = await build_signal_quality_from_db(ctx.race_weekend.circuit_key)
        if sq:
            ctx = evolve_race_context(ctx, signal_quality=sq)
            self._commit(ctx)
        result = await run_race_monitor(ctx, self._deps)
        self._commit(result)

    async def run_scorer_and_learner(self, race_key: str) -> None:
        """Agent 5 — post-race scoring and learning."""
        ctx = self._bootstrap_context(race_key)
        if ctx is None:
            return
        result = await run_agent(
            run_scorer_and_learner,
            ctx,
            self._deps,
            agent_name="Agent5-ScorerLearner",
            budget_s=AGENT5_BUDGET_S,
        )
        self._commit(result)
