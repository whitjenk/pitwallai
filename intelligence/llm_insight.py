"""Bring-your-own-LLM insight layer.

Turns the deterministic, rules-computed facts (pace, projected points, chip
window, budget) into a short, sharp natural-language tip. The LLM never
computes numbers — it is given the facts and asked to synthesise insight from
them only, so the output stays factual and cannot hallucinate stats.

Everything here is best-effort: when BYO mode is off, or the provider is
unreachable, or the guardrail blocks a billed model, the functions return None
and callers fall back to the existing rules text.
"""

from __future__ import annotations

import os

from loguru import logger

from pitwallai.llm_mode import byo_llm_enabled

_SYSTEM_PROMPT = (
    "You are a sharp, concise F1 Fantasy analyst. You are given STRUCTURED FACTS "
    "about a recommendation that were computed from live timing and price data. "
    "Write ONE insightful sentence (max ~30 words) the player can act on.\n"
    "STRICT RULES:\n"
    "- Use ONLY the facts provided. Never invent lap times, grid positions, "
    "points, prices, or driver form that are not in the facts.\n"
    "- No preamble, no greeting, no emoji, no markdown. Just the sentence.\n"
    "- If the facts are thin, say what they do support without overclaiming."
)


def _build_agent():
    """Construct a Pydantic AI agent for the configured BYO provider, or None."""
    from pydantic_ai import Agent

    from pitwallai.agents.radio_intercept.config import PitWallSettings
    from pitwallai.agents.radio_intercept.model_factory import get_model

    settings = PitWallSettings.from_env()
    provider = os.getenv("PITWALL_LLM_PROVIDER", "ollama").strip().lower() or "ollama"
    model = get_model(
        provider,
        settings.llm_api_key(),
        model_name=settings.llm_model or None,
        use_vertex=settings.llm_use_vertex,
        ollama_base_url=settings.ollama_base_url,
    )
    return Agent(model, system_prompt=_SYSTEM_PROMPT, output_type=str)


async def llm_tip(facts: str) -> str | None:
    """
    Return a one-sentence grounded insight for the given facts, or None.

    Args:
        facts: Plain-text structured facts (already computed deterministically).

    Returns:
        A short insight string, or None to fall back to rules text.
    """
    if not byo_llm_enabled():
        return None
    if not facts.strip():
        return None
    try:
        agent = _build_agent()
        result = await agent.run(facts)
        text = (result.output or "").strip()
    except Exception as exc:  # noqa: BLE001 — insight is strictly optional
        logger.warning("llm_insight unavailable, falling back to rules: {}", exc)
        return None
    if not text:
        return None
    # One tidy sentence; strip any stray quoting/markdown the model added.
    text = text.strip().strip('"').strip()
    return text[:280]
