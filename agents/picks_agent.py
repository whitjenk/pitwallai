"""PicksAgent — the unified Saturday-broadcast agent.

What used to be three separately-named agents (Context Builder,
Practice Analyst, Quali Strategist) are now three *stages* of one logical
agent that owns the entire pre-lock picks lifecycle. This is the
3-agent ontology:

    PicksAgent     — Thu context → Fri practice → Sat quali picks
    RaceMonitor    — Sun live race watching (separate latency contract)
    ScorerLearner  — post-race scoring + eval (separate concern)

Stage functions remain modular for testability — they live in their
existing modules. PicksAgent is the *interface*: one named entry, one
versioned pipeline, stage-tagged logs so calibration drift is attributable
to which stage drifted.
"""

from __future__ import annotations

from enum import Enum

from loguru import logger

from agents.base import (
    AGENT1_BUDGET_S,
    AGENT2_BUDGET_S,
    AGENT3_BUDGET_S,
    AgentRunDependencies,
    run_agent,
)
from agents.context_builder import run_context_builder
from agents.practice_analyst import run_practice_analyst
from agents.quali_strategist import run_quali_strategist
from orchestrator.race_context import RaceContext


class PicksStage(str, Enum):
    """Three stages of the unified PicksAgent. Tag every log + version stamp."""

    CONTEXT = "context"     # Thursday — circuit history, weather, FIA directives
    PRACTICE = "practice"   # Friday — FP1/FP2 telemetry, radio, anomalies
    QUALI = "quali"         # Saturday — transfer combinations → picks


_STAGE_BUDGETS: dict[PicksStage, int] = {
    PicksStage.CONTEXT: AGENT1_BUDGET_S,
    PicksStage.PRACTICE: AGENT2_BUDGET_S,
    PicksStage.QUALI: AGENT3_BUDGET_S,
}

_STAGE_RUNNERS = {
    PicksStage.CONTEXT: run_context_builder,
    PicksStage.PRACTICE: run_practice_analyst,
    PicksStage.QUALI: run_quali_strategist,
}


class PicksAgent:
    """Single named agent over the three Saturday-broadcast stages."""

    def __init__(self, deps: AgentRunDependencies) -> None:
        self._deps = deps

    async def run_stage(self, stage: PicksStage, ctx: RaceContext) -> RaceContext:
        """Run one stage under its time budget. Stage-tagged logs."""
        runner = _STAGE_RUNNERS[stage]
        agent_label = f"PicksAgent-{stage.value}"
        logger.bind(
            picks_stage=stage.value,
            race_key=ctx.race_weekend.race_key,
        ).info("picks_agent_stage_starting")
        result = await run_agent(
            runner,
            ctx,
            self._deps,
            agent_name=agent_label,
            budget_s=_STAGE_BUDGETS[stage],
        )
        logger.bind(
            picks_stage=stage.value,
            race_key=ctx.race_weekend.race_key,
        ).info("picks_agent_stage_complete")
        return result
