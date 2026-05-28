"""Shared pytest fixtures for PitWallAI tests."""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from pitwallai.agents.radio_intercept.agent import RadioInterceptAgent
from pitwallai.agents.radio_intercept.models import AgentDependencies, WebSocketEvent
from pitwallai.agents.radio_intercept.seed_data import JARGON_GLOSSARY, TEAM_COLORS
from pitwallai.agents.radio_intercept.stream_handler import RadioInterceptDecoder
from pitwallai.agents.radio_intercept.vector_store import MockVectorStore


@pytest.fixture(scope="module")
def vector_store() -> MockVectorStore:
    """Module-scoped vector store."""
    return MockVectorStore()


@pytest.fixture(scope="module")
def agent() -> RadioInterceptAgent:
    """Module-scoped decoder agent (rules backend)."""
    return RadioInterceptAgent()


@pytest.fixture
def agent_deps(vector_store: MockVectorStore) -> AgentDependencies:
    """Per-test agent dependencies."""
    return AgentDependencies(
        vector_store=vector_store,
        session_key=9158,
        jargon_glossary=JARGON_GLOSSARY,
        team_colors=TEAM_COLORS,
    )


@pytest_asyncio.fixture
async def decoder(
    agent: RadioInterceptAgent,
    vector_store: MockVectorStore,
) -> RadioInterceptDecoder:
    """Function-scoped decoder with mock output queue."""
    dec = RadioInterceptDecoder(agent=agent, vector_store=vector_store)
    dec._running = True
    dec._deps.session_key = 9158
    yield dec
    dec._running = False


@pytest.fixture
def output_queue() -> asyncio.Queue[WebSocketEvent]:
    """Subscriber queue for decoded events."""
    return asyncio.Queue(maxsize=100)
