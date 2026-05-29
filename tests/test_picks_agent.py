"""Tests for the PicksAgent abstraction (3-stage Saturday pipeline)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agents.picks_agent import PicksAgent, PicksStage
from pitwallai.version import PIPELINE_VERSION


def test_pipeline_version_matches_consolidation() -> None:
    assert PIPELINE_VERSION.startswith("3-agent")


def test_picks_stage_enum_has_three_stages() -> None:
    assert {s.value for s in PicksStage} == {"context", "practice", "quali"}


@pytest.mark.asyncio
async def test_picks_agent_delegates_to_stage_runner_with_label() -> None:
    deps = object()  # not introspected by the wrapper
    ctx = type("Ctx", (), {"race_weekend": type("W", (), {"race_key": "2026_monaco"})()})()

    fake_runner = AsyncMock(return_value=ctx)
    with patch.dict(
        "agents.picks_agent._STAGE_RUNNERS",
        {PicksStage.CONTEXT: fake_runner},
    ):
        with patch("agents.picks_agent.run_agent", new=AsyncMock(return_value=ctx)) as wrapped:
            agent = PicksAgent(deps)  # type: ignore[arg-type]
            result = await agent.run_stage(PicksStage.CONTEXT, ctx)

    assert result is ctx
    call_kwargs = wrapped.call_args.kwargs
    # The agent label is the canonical drift-attribution string we care about.
    assert call_kwargs["agent_name"] == "PicksAgent-context"


@pytest.mark.asyncio
async def test_picks_agent_uses_per_stage_budget() -> None:
    from agents.base import AGENT2_BUDGET_S
    from agents.picks_agent import _STAGE_BUDGETS

    assert _STAGE_BUDGETS[PicksStage.PRACTICE] == AGENT2_BUDGET_S
