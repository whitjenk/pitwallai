"""Bring-your-own-LLM mode toggle and insight-layer fallback behaviour."""

from __future__ import annotations

import pytest

import intelligence.llm_insight as li
from pitwallai import llm_mode


def test_mode_defaults_to_free(monkeypatch) -> None:
    monkeypatch.delenv("PITWALL_LLM_MODE", raising=False)
    assert llm_mode.llm_mode() == "free"
    assert llm_mode.byo_llm_enabled() is False
    assert "free" in llm_mode.active_llm_label()


def test_mode_byo_enables(monkeypatch) -> None:
    monkeypatch.setenv("PITWALL_LLM_MODE", "byo")
    monkeypatch.setenv("PITWALL_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("PITWALL_LLM_MODEL", "llama3.2")
    assert llm_mode.byo_llm_enabled() is True
    assert "BYO" in llm_mode.active_llm_label()
    assert "ollama" in llm_mode.active_llm_label()


@pytest.mark.asyncio
async def test_tip_none_when_free(monkeypatch) -> None:
    monkeypatch.delenv("PITWALL_LLM_MODE", raising=False)
    assert await li.llm_tip("Recommend HAM, projected +13 pts.") is None


@pytest.mark.asyncio
async def test_tip_uses_llm_when_byo(monkeypatch) -> None:
    from pydantic_ai import Agent
    from pydantic_ai.models.test import TestModel

    monkeypatch.setenv("PITWALL_LLM_MODE", "byo")
    monkeypatch.setattr(
        li,
        "_build_agent",
        lambda: Agent(
            TestModel(custom_output_text="HAM's P1 practice pace makes the swap the clear play."),
            system_prompt=li._SYSTEM_PROMPT,
            output_type=str,
        ),
    )
    tip = await li.llm_tip("Recommend HAM, projected +13 pts, confidence 81%.")
    assert tip == "HAM's P1 practice pace makes the swap the clear play."


def test_grounding_allows_facts_and_places() -> None:
    g = li._is_grounded
    allowed = {"HAM", "ANT"}
    assert g("Swap ANT for HAM given HAM's strong practice pace.", allowed) is True
    assert g("Antonelli is slower than Hamilton on pace.", allowed) is True
    assert g("HAM's run at Monaco Grand Prix looks strong.", allowed) is True


def test_grounding_rejects_offfact_and_fabricated_drivers() -> None:
    g = li._is_grounded
    allowed = {"HAM", "ANT"}
    assert g("Leclerc's pace suggests ANT struggling.", allowed) is False  # LEC not allowed
    assert g("VER looks strong this weekend.", allowed) is False  # VER not allowed
    assert g("Swap Antoine Hubert to Lewis Hamilton.", allowed) is False  # fabricated name


@pytest.mark.asyncio
async def test_tip_rejected_when_off_fact_driver(monkeypatch) -> None:
    from pydantic_ai import Agent
    from pydantic_ai.models.test import TestModel

    monkeypatch.setenv("PITWALL_LLM_MODE", "byo")
    monkeypatch.setattr(
        li,
        "_build_agent",
        lambda: Agent(
            TestModel(custom_output_text="Leclerc will beat ANT easily this weekend."),
            system_prompt=li._SYSTEM_PROMPT,
            output_type=str,
        ),
    )
    # LEC is not in allowed -> hallucination guard drops it -> rules fallback.
    assert await li.llm_tip("HAM vs ANT.", allowed_codes={"HAM", "ANT"}) is None


@pytest.mark.asyncio
async def test_tip_graceful_when_provider_unreachable(monkeypatch) -> None:
    monkeypatch.setenv("PITWALL_LLM_MODE", "byo")

    def _boom():
        raise RuntimeError("connection refused")

    monkeypatch.setattr(li, "_build_agent", _boom)
    assert await li.llm_tip("Recommend HAM.") is None
