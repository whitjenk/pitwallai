"""End-to-end pipeline tests without HTTP server."""

from __future__ import annotations

import pytest

from pitwallai.agents.radio_intercept.enums import (
    ConfirmationState,
    RadioIntent,
    StrategicSignal,
    UrgencyLevel,
)
from pitwallai.agents.radio_intercept.models import AgentDependencies, RadioRawMessage
from pitwallai.agents.radio_intercept.seed_data import MONACO_REHEARSAL_SCENARIO

DIRECTIVE_WORDS = ("box now", "you should", "pit now", "must", "immediately")


@pytest.mark.asyncio
async def test_monaco_event6_triggers_competitor_intel(
    agent,
    agent_deps: AgentDependencies,
) -> None:
    """Event 6 must produce Ferrari pit intel with high urgency."""
    message = MONACO_REHEARSAL_SCENARIO.events[5]
    result = await agent.decode(message, agent_deps)

    assert result.decoded_intent == RadioIntent.PIT_CALL
    assert result.competitor_intel is not None
    assert result.competitor_intel.target_team == "Ferrari"
    assert result.competitor_intel.confirmation_state == ConfirmationState.UNCONFIRMED
    assert result.urgency_level in (UrgencyLevel.HIGH, UrgencyLevel.CRITICAL)


@pytest.mark.asyncio
async def test_monaco_event9_is_critical(
    agent,
    agent_deps: AgentDependencies,
) -> None:
    """Event 9 must be critical tire degradation."""
    message = MONACO_REHEARSAL_SCENARIO.events[8]
    result = await agent.decode(message, agent_deps)

    assert result.decoded_intent == RadioIntent.TIRE_COMPLAINT
    assert result.urgency_level == UrgencyLevel.CRITICAL
    assert result.strategic_signal == StrategicSignal.TIRE_DEGRADATION_HIGH
    assert result.confidence_score >= 0.8


@pytest.mark.asyncio
async def test_evidence_summary_is_not_directive(
    agent,
    agent_deps: AgentDependencies,
) -> None:
    """Evidence summaries must not contain directive language."""
    for message in MONACO_REHEARSAL_SCENARIO.events:
        result = await agent.decode(message, agent_deps)
        if result.evidence_summary is None:
            continue
        lowered = result.evidence_summary.lower()
        for word in DIRECTIVE_WORDS:
            assert word not in lowered, f"Directive '{word}' in: {result.evidence_summary}"


@pytest.mark.asyncio
async def test_latency_target(
    agent,
    agent_deps: AgentDependencies,
) -> None:
    """All Monaco decodes complete within CI latency budget."""
    for message in MONACO_REHEARSAL_SCENARIO.events:
        result = await agent.decode(message, agent_deps)
        assert result.processing_latency_ms is not None
        assert result.processing_latency_ms < 1500


@pytest.mark.asyncio
async def test_all_transmissions_have_team_color(
    agent,
    agent_deps: AgentDependencies,
) -> None:
    """Every decode must include a hex team color."""
    for message in MONACO_REHEARSAL_SCENARIO.events:
        result = await agent.decode(message, agent_deps)
        assert result.team_color
        assert result.team_color.startswith("#")
