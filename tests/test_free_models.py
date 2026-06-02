"""Free-models-only guardrail: never construct a billed model by default."""

from __future__ import annotations

import pytest

from pitwallai.free_models import (
    PaidModelBlockedError,
    assert_free_model,
    free_models_only,
    is_free_model,
)


def test_default_is_free_only_on(monkeypatch) -> None:
    monkeypatch.delenv("PITWALL_FREE_MODELS_ONLY", raising=False)
    assert free_models_only() is True


@pytest.mark.parametrize(
    ("provider", "model", "use_vertex", "api_key", "free"),
    [
        ("gemini", "gemini-2.0-flash", False, "key", True),   # AI Studio flash + key
        ("gemini", "gemini-1.5-flash", False, "key", True),
        ("gemini", "gemini-2.0-flash", True, "key", False),   # Vertex bills
        ("gemini", "gemini-2.0-flash", False, "", False),     # no key
        ("gemini", "gemini-1.5-pro", False, "key", False),    # Pro not free
        ("ollama", "llama3.2", False, "", True),              # local
        ("openai", "gpt-4o-mini", False, "key", False),       # paid
        ("claude", "claude-3-5-sonnet-latest", False, "key", False),
    ],
)
def test_is_free_model_matrix(provider, model, use_vertex, api_key, free) -> None:
    assert is_free_model(provider, model, use_vertex=use_vertex, api_key=api_key) is free


def test_assert_free_model_blocks_paid_when_on(monkeypatch) -> None:
    monkeypatch.setenv("PITWALL_FREE_MODELS_ONLY", "1")
    with pytest.raises(PaidModelBlockedError):
        assert_free_model("claude", "claude-3-5-sonnet-latest", use_vertex=False, api_key="k")
    with pytest.raises(PaidModelBlockedError):
        assert_free_model("gemini", "gemini-2.0-flash", use_vertex=True, api_key="k")


def test_assert_free_model_noop_when_off(monkeypatch) -> None:
    monkeypatch.setenv("PITWALL_FREE_MODELS_ONLY", "0")
    assert_free_model("openai", "gpt-4o-mini", use_vertex=False, api_key="k")  # no raise


def test_get_model_blocks_paid_providers_by_default(monkeypatch) -> None:
    monkeypatch.delenv("PITWALL_FREE_MODELS_ONLY", raising=False)
    from pitwallai.agents.radio_intercept.model_factory import get_model

    with pytest.raises(PaidModelBlockedError):
        get_model("openai", "test-key")
    with pytest.raises(PaidModelBlockedError):
        get_model("claude", "test-key")
    # Gemini via Vertex (default use_vertex=True) is also billed → blocked.
    with pytest.raises(PaidModelBlockedError):
        get_model("gemini", "")


def test_config_forces_non_vertex_when_free_only(monkeypatch) -> None:
    monkeypatch.setenv("PITWALL_FREE_MODELS_ONLY", "1")
    monkeypatch.setenv("PITWALL_LLM_USE_VERTEX", "true")
    from pitwallai.agents.radio_intercept.config import PitWallSettings

    settings = PitWallSettings.from_env()
    assert settings.llm_use_vertex is False
