"""Shared agent contracts, dependencies, and time budgets."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from loguru import logger
from pydantic import BaseModel, ConfigDict

from openf1.client import OpenF1Client
from orchestrator.race_context import RaceContext
from pitwallai.agents.radio_intercept.agent import RadioInterceptAgent
from pitwallai.agents.radio_intercept.config import PitWallSettings
from pitwallai.agents.radio_intercept.vector_store import MockVectorStore

T = TypeVar("T")

AGENT1_BUDGET_S = 90
AGENT2_BUDGET_S = 120
AGENT3_BUDGET_S = 60
AGENT5_BUDGET_S = 120


class AgentOutput(BaseModel):
    """Base marker for agent Pydantic outputs."""

    model_config = ConfigDict(frozen=True)


@dataclass(frozen=True, slots=True)
class AgentRunDependencies:
    """
    Typed dependency injection for Phase 6 agents.

    Mirrors RadioIntercept ``AgentDependencies`` pattern at orchestration layer.
    """

    openf1_client: OpenF1Client
    radio_agent: RadioInterceptAgent
    vector_store: MockVectorStore
    settings: PitWallSettings


async def run_with_budget(
    coro: Awaitable[T],
    *,
    agent_name: str,
    budget_s: float,
    race_key: str,
    fallback: T | None = None,
) -> T:
    """
    Run an agent coroutine within a time budget.

    On timeout, logs a warning and returns fallback if provided.
  """
    try:
        return await asyncio.wait_for(coro, timeout=budget_s)
    except asyncio.TimeoutError:
        logger.warning(
            "{} exceeded {}s budget race_key={}",
            agent_name,
            budget_s,
            race_key,
        )
        if fallback is not None:
            return fallback
        raise


async def run_agent(
    fn: Callable[[RaceContext, AgentRunDependencies], Awaitable[RaceContext]],
    ctx: RaceContext,
    deps: AgentRunDependencies,
    *,
    agent_name: str,
    budget_s: float,
) -> RaceContext:
    """Execute an agent function under budget, returning best-effort context."""
    race_key = ctx.race_weekend.race_key
    try:
        return await run_with_budget(
            fn(ctx, deps),
            agent_name=agent_name,
            budget_s=budget_s,
            race_key=race_key,
            fallback=ctx,
        )
    except Exception as exc:
        logger.exception("{} failed race_key={}: {}", agent_name, race_key, exc)
        return ctx
