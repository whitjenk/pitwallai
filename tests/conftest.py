"""Shared pytest fixtures for PitWallAI test suite."""

from __future__ import annotations

import pytest
import pytest_asyncio

from pitwallai.agents.radio_intercept.agent import RadioInterceptAgent
from pitwallai.agents.radio_intercept.models import AgentDependencies
from pitwallai.agents.radio_intercept.seed_data import JARGON_GLOSSARY, TEAM_COLORS
from pitwallai.agents.radio_intercept.stream_handler import RadioInterceptDecoder
from pitwallai.agents.radio_intercept.vector_store import MockVectorStore


@pytest.fixture(scope="module")
def vector_store() -> MockVectorStore:
    """
    Module-scoped vector store.

    The embedding model loads once per test module, not once per test.
    """
    return MockVectorStore()


@pytest.fixture(scope="module")
def agent() -> RadioInterceptAgent:
    """
    Module-scoped decoder agent (rules backend — no API key, no LLM calls).
    """
    return RadioInterceptAgent()


@pytest.fixture(scope="function")
def agent_deps(vector_store: MockVectorStore) -> AgentDependencies:
    """
    Fresh AgentDependencies per test to prevent state bleed between tests.
    """
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
    """
    Function-scoped decoder with async teardown via stop().
    """
    dec = RadioInterceptDecoder(agent=agent, vector_store=vector_store)
    dec._running = True
    yield dec
    await dec.stop()
