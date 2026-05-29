"""LLM provider contract tests (mocked — no live API calls)."""

from __future__ import annotations

import importlib
import importlib.util
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

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

from pitwallai.agents.radio_intercept.config import PitWallSettings
from pitwallai.agents.radio_intercept.decoder_factory import (
    _sanitise_evidence_summary,
    apply_llm_output_guards,
)
from pitwallai.agents.radio_intercept.enums import RadioIntent, StrategicSignal, UrgencyLevel
from pitwallai.agents.radio_intercept.llm_decoder import LLMDecoder, _create_llm_agent
from pitwallai.agents.radio_intercept.model_factory import get_model
from pitwallai.agents.radio_intercept.models import AgentDependencies, DecodedTransmission
from pitwallai.agents.radio_intercept.seed_data import MONACO_REHEARSAL_SCENARIO


def _llm_payload(*, evidence_summary: str | None) -> DecodedTransmission:
    """Build a structurally valid DecodedTransmission as if from an LLM."""
    event = MONACO_REHEARSAL_SCENARIO.events[0]
    return DecodedTransmission(
        session_key=event.session_key,
        driver_number=event.driver_number,
        driver_code=event.driver_code,
        team=event.team,
        timestamp=event.timestamp,
        raw_transcript=event.raw_transcript,
        decoded_intent=RadioIntent.GAP_UPDATE_REQUEST,
        jargon_decoded=[],
        strategic_signal=StrategicSignal.NEUTRAL,
        urgency_level=UrgencyLevel.LOW,
        confidence_score=0.82,
        competitor_intel=None,
        evidence_summary=evidence_summary,
        team_color="#FF8000",
        context_doc_ids=[],
        model_reasoning="mock",
    )


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
def test_get_model_returns_expected_class(provider: str, expected_class_path: str) -> None:
    """Each provider maps to the correct Pydantic AI model wrapper."""
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


def test_create_llm_agent_uses_shared_output_schema() -> None:
    """Agent is bound to DecodedTransmission for every provider."""
    stub_model = MagicMock(spec=Model)
    with patch("pitwallai.agents.radio_intercept.llm_decoder.Agent") as mock_agent_cls:
        mock_agent_cls.return_value = MagicMock()
        _create_llm_agent(stub_model)
        mock_agent_cls.assert_called_once()
        call_kwargs = mock_agent_cls.call_args.kwargs
        assert call_kwargs["deps_type"] is AgentDependencies
        assert call_kwargs.get("output_type") is DecodedTransmission or (
            call_kwargs.get("result_type") is DecodedTransmission
        )


@pytest.mark.parametrize("provider", ["gemini", "claude", "openai", "ollama"])
@pytest.mark.asyncio
async def test_llm_decode_output_schema_consistent_across_providers(
    provider: str,
    agent_deps: AgentDependencies,
    decoded_transmission: DecodedTransmission,
) -> None:
    """Mocked LLM path returns the same DecodedTransmission schema for all providers."""
    settings = replace(
        PitWallSettings.from_env(),
        llm_provider=provider,
        llm_model="gemini-2.0-flash",
    )

    message = MONACO_REHEARSAL_SCENARIO.events[0]
    mock_run = MagicMock()
    mock_run.output = decoded_transmission

    mock_agent = MagicMock()
    mock_agent.run_async = AsyncMock(return_value=mock_run)

    with (
        patch("pitwallai.agents.radio_intercept.llm_decoder.get_model", return_value=MagicMock(spec=Model)),
        patch(
            "pitwallai.agents.radio_intercept.llm_decoder._create_llm_agent",
            return_value=mock_agent,
        ),
    ):
        decoder = LLMDecoder(settings)
        result = await decoder.decode(message, agent_deps)

    assert isinstance(result, DecodedTransmission)
    assert result.decoded_intent == decoded_transmission.decoded_intent
    assert result.confidence_score == decoded_transmission.confidence_score
    assert result.transmission_id is not None
    assert result.processing_latency_ms is not None


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
    result = _sanitise_evidence_summary(raw)
    if expected_fragment is None:
        assert result is None
    else:
        assert result is not None
        assert expected_fragment in result
        lowered = result.lower()
        for banned in ("you should", "pit now", "recommend", "immediately"):
            assert banned not in lowered


def test_apply_llm_output_guards_on_decoded_transmission(
    decoded_transmission: DecodedTransmission,
) -> None:
    """Boundary guard rewrites evidence_summary on the transmission object."""
    dirty = decoded_transmission.model_copy(
        update={"evidence_summary": "You should box now. Gap closing on rival."}
    )
    cleaned = apply_llm_output_guards(dirty)
    assert cleaned.evidence_summary is not None
    assert "you should" not in cleaned.evidence_summary.lower()
    assert "box now" not in cleaned.evidence_summary.lower()
