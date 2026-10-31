"""Shared pytest fixtures for PitWallAI test suite."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _reset_spend_guard_cache():
    """Reset the module-level spend-guard cache around every test.

    ``intelligence.spend_guard`` caches a process-wide snapshot in a module
    global. Tests that drive it into a DEGRADED (over-cap) state — e.g.
    ``test_spend_guard`` / ``test_beta_launch`` — would otherwise leak that
    state into later tests (``check_vision_budget`` reads the same cache and
    would wrongly report ``monthly_spend_cap``). Reset to the fail-open
    default before and after each test so ordering can't matter.
    """
    import intelligence.spend_guard as sg

    sg._cache = None
    sg._cache_loaded_at = 0.0
    yield
    sg._cache = None
    sg._cache_loaded_at = 0.0


@pytest.fixture
def mock_openf1_client() -> MagicMock:
    """Stand-in OpenF1 client object for tests that need one without a live connection."""
    client = MagicMock(name="openf1_client")
    client.__aiter__ = MagicMock(return_value=iter([]))
    return client
