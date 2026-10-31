"""LLM provider contract tests (mocked — no live API calls)."""

from __future__ import annotations

import importlib
import importlib.util
from unittest.mock import MagicMock, patch

import pytest
from pydantic_ai.models import Model


def _adapter_importable(class_path: str) -> bool:
    """True if the provider's Pydantic AI adapter module can be imported.

    Provider adapters (anthropic, google, openai) are optional extras whose
    importability depends on the installed dependency set. A provider whose
    adapter can't import is skipped rather than failing CI — the default
    install ships gemini + openai; claude is a BYOK extra. See
    requirements.txt for the version coupling.
    """
    module_path = class_path.rsplit(".", 1)[0]
    try:
        if importlib.util.find_spec(module_path) is None:
            return False
        importlib.import_module(module_path)
    except Exception:
        return False
    return True


from pitwallai.llm.model_factory import get_model
from pitwallai.llm.sanitize import sanitise_evidence_summary


def _provider_param(provider: str, class_path: str) -> "pytest.ParameterSet":
    """Parametrize row that skips when the provider adapter can't import."""
    return pytest.param(
        provider,
        class_path,
        marks=pytest.mark.skipif(
            not _adapter_importable(class_path),
            reason=f"{provider} adapter ({class_path.rsplit('.', 1)[0]}) not importable",
        ),
    )


@pytest.mark.parametrize(
    ("provider", "expected_class_path"),
    [
        _provider_param("gemini", "pydantic_ai.models.google.GoogleModel"),
        _provider_param("claude", "pydantic_ai.models.anthropic.AnthropicModel"),
        _provider_param("openai", "pydantic_ai.models.openai.OpenAIModel"),
        _provider_param("ollama", "pydantic_ai.models.openai.OpenAIModel"),
    ],
)
def test_get_model_returns_expected_class(
    provider: str, expected_class_path: str, monkeypatch
) -> None:
    """Each provider maps to the correct Pydantic AI model wrapper."""
    # This exercises factory wiring for paid providers too — opt out of the
    # free-models-only guard (no real API calls happen; providers are patched).
    monkeypatch.setenv("PITWALL_FREE_MODELS_ONLY", "0")
    with patch(expected_class_path) as mock_cls:
        mock_cls.return_value = MagicMock(spec=Model)
        if provider == "gemini":
            with patch("pydantic_ai.providers.google.GoogleProvider"):
                model = get_model(provider, "test-key", use_vertex=False)
        elif provider == "claude":
            with patch("pydantic_ai.providers.anthropic.AnthropicProvider"):
                model = get_model(provider, "test-key")
        else:
            with patch("pydantic_ai.providers.openai.OpenAIProvider"):
                model = get_model(provider, "test-key")
        assert model is mock_cls.return_value
        mock_cls.assert_called_once()


@pytest.mark.parametrize(
    ("raw", "expected_fragment"),
    [
        ("You should box now — Ferrari pit activity observed.", "Ferrari pit activity observed"),
        ("Recommend pitting immediately. Gap is 2.1s.", "Gap is 2.1s"),
        ("Pit now. Leclerc boxing.", "Leclerc boxing"),
        (None, None),
    ],
)
def test_sanitise_evidence_summary_strips_directives(
    raw: str | None,
    expected_fragment: str | None,
) -> None:
    """Directive phrases and imperative sentences are removed from evidence."""
    result = sanitise_evidence_summary(raw)
    if expected_fragment is None:
        assert result is None
    else:
        assert result is not None
        assert expected_fragment in result
        lowered = result.lower()
        for banned in ("you should", "pit now", "recommend", "immediately"):
            assert banned not in lowered
