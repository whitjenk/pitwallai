"""Shared pytest fixtures for PitWallAI test suite."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from pitwallai.agents.radio_intercept.agent import RadioInterceptAgent
from pitwallai.agents.radio_intercept.enums import RadioIntent, StrategicSignal, UrgencyLevel
from pitwallai.agents.radio_intercept.models import AgentDependencies, DecodedTransmission
from pitwallai.agents.radio_intercept.seed_data import JARGON_GLOSSARY, TEAM_COLORS
from pitwallai.agents.radio_intercept.stream_handler import RadioInterceptDecoder
from pitwallai.agents.radio_intercept.vector_store import MockVectorStore


@pytest.fixture(scope="module")
def chroma_db() -> MockVectorStore:
    """
    In-memory ChromaDB-backed vector store (module-scoped).

    Loads the embedding model once per test module.
    """
    return MockVectorStore()


@pytest.fixture(scope="module")
def vector_store(chroma_db: MockVectorStore) -> MockVectorStore:
    """Alias for chroma_db — used by e2e and resilience tests."""
    return chroma_db


@pytest.fixture(scope="module")
def agent() -> RadioInterceptAgent:
    """Rules-backend decoder agent (no API key, no LLM calls)."""
    return RadioInterceptAgent()


@pytest.fixture(scope="function")
def agent_deps(vector_store: MockVectorStore) -> AgentDependencies:
    """Fresh AgentDependencies per test to prevent cross-test state bleed."""
    return AgentDependencies(
        vector_store=vector_store,
        session_key=9158,
        jargon_glossary=JARGON_GLOSSARY,
        team_colors=TEAM_COLORS,
    )


@pytest.fixture
def decoded_transmission() -> DecodedTransmission:
    """Minimal valid DecodedTransmission for unit assertions and mocks."""
    return DecodedTransmission(
        session_key=9158,
        driver_number=4,
        driver_code="NOR",
        team="McLaren",
        timestamp=datetime(2024, 5, 26, 14, 35, 0, tzinfo=UTC),
        raw_transcript="Gap is 2.1 seconds.",
        decoded_intent=RadioIntent.GAP_UPDATE_REQUEST,
        jargon_decoded=[],
        strategic_signal=StrategicSignal.NEUTRAL,
        urgency_level=UrgencyLevel.LOW,
        confidence_score=0.85,
        competitor_intel=None,
        evidence_summary="Driver reports a 2.1s gap to the car ahead.",
        team_color="#FF8000",
        context_doc_ids=[],
        model_reasoning="rules:test",
        processing_latency_ms=12.5,
    )


@pytest.fixture
def mock_openf1_client() -> MagicMock:
    """
    Stand-in for an OpenF1 WebSocket client.

    Resilience tests patch websockets.connect directly; this fixture is available
    for tests that need a mock client object without a live connection.
    """
    client = MagicMock(name="openf1_ws_client")
    client.__aiter__ = MagicMock(return_value=iter([]))
    return client


@pytest_asyncio.fixture
async def decoder(
    agent: RadioInterceptAgent,
    vector_store: MockVectorStore,
) -> RadioInterceptDecoder:
    """Function-scoped decoder with async teardown via stop()."""
    dec = RadioInterceptDecoder(agent=agent, vector_store=vector_store)
    dec._running = True
    yield dec
    await dec.stop()
