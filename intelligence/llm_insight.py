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
import re

from loguru import logger

from pitwallai.llm_mode import byo_llm_enabled

# 2026 grid surname per code — used ONLY to (a) give the model the correct name
# for each driver in the facts and (b) reject insights that name a driver who is
# not part of the recommendation (the free-model failure mode).
_ROSTER_2026: dict[str, str] = {
    "NOR": "Norris", "VER": "Verstappen", "BOR": "Bortoleto", "HAD": "Hadjar",
    "GAS": "Gasly", "PER": "Perez", "ANT": "Antonelli", "ALO": "Alonso",
    "LEC": "Leclerc", "STR": "Stroll", "ALB": "Albon", "HUL": "Hulkenberg",
    "LAW": "Lawson", "OCO": "Ocon", "LIN": "Lindblad", "COL": "Colapinto",
    "HAM": "Hamilton", "SAI": "Sainz", "RUS": "Russell", "BOT": "Bottas",
    "PIA": "Piastri", "BEA": "Bearman",
}
_KNOWN_CODES = frozenset(_ROSTER_2026)


def driver_name(code: str) -> str:
    """Real driver name for a code (e.g. 'HAM (Hamilton)'), or just the code."""
    surname = _ROSTER_2026.get(code.upper())
    return f"{code.upper()} ({surname})" if surname else code.upper()


def _is_grounded(tip: str, allowed_codes: set[str]) -> bool:
    """Reject insights that reference a driver outside the recommendation.

    Catches the free-model failure mode: expanding a code to the wrong name, or
    inventing a driver who was never in the facts.
    """
    allowed = {c.upper() for c in allowed_codes}
    allowed_surnames = {_ROSTER_2026[c] for c in allowed if c in _ROSTER_2026}
    # 1) No driver CODE outside the allowed set.
    for token in re.findall(r"\b[A-Z]{3}\b", tip):
        if token in _KNOWN_CODES and token not in allowed:
            return False
    # 2) No driver SURNAME whose code is not allowed.
    lower = tip.lower()
    for code, surname in _ROSTER_2026.items():
        if code not in allowed and surname.lower() in lower:
            return False
    # 3) No "Firstname Lastname" person whose surname is not an allowed driver —
    #    catches a code wrongly expanded to a fabricated name (e.g. ANT ->
    #    "Antoine Hubert"). F1 weekend/place words are excluded.
    for first, last in re.findall(r"\b([A-Z][a-z]+)\s+([A-Z][a-z]+)\b", tip):
        if last in _NON_NAME_WORDS or first in _NON_NAME_WORDS:
            continue
        if last not in allowed_surnames:
            return False
    return True


# Capitalised words that legitimately pair up in F1 prose (not driver names).
_NON_NAME_WORDS = frozenset({
    "Grand", "Prix", "Monaco", "Practice", "Qualifying", "Sunday", "Saturday",
    "Friday", "Las", "Vegas", "Abu", "Dhabi", "Sao", "Paulo", "Grid", "Race",
    "Pole", "Limitless", "Wildcard", "Fantasy", "Free",
})

_SYSTEM_PROMPT = (
    "You are a sharp, concise F1 Fantasy analyst. You are given STRUCTURED FACTS "
    "about a recommendation that were computed from live timing and price data. "
    "Write ONE insightful sentence (max ~30 words) the player can act on.\n"
    "STRICT RULES:\n"
    "- Use ONLY the facts provided. Never invent lap times, grid positions, "
    "points, prices, or driver form that are not in the facts.\n"
    "- Refer to drivers by the EXACT 3-letter code given (e.g. HAM, ANT, LEC). "
    "Never expand a code into a full name — you will get the name wrong.\n"
    "- No preamble, no greeting, no emoji, no markdown. Just the sentence.\n"
    "- If the facts are thin, say what they do support without overclaiming."
)


def _build_agent_for(system_prompt: str):
    """Construct a Pydantic AI agent for the configured BYO provider + a prompt."""
    from pydantic_ai import Agent

    from pitwallai.agents.radio_intercept.config import PitWallSettings
    from pitwallai.agents.radio_intercept.model_factory import get_model

    settings = PitWallSettings.from_env()
    provider = os.getenv("PITWALL_LLM_PROVIDER", "ollama").strip().lower() or "ollama"
    # Read the model name straight from env: the legacy settings parser splits on
    # ":" as provider:model, which mangles Ollama version tags like "llama3.1:8b".
    model_name = os.getenv("PITWALL_LLM_MODEL", "").strip() or None
    model = get_model(
        provider,
        settings.llm_api_key(),
        model_name=model_name,
        use_vertex=settings.llm_use_vertex,
        ollama_base_url=settings.ollama_base_url,
    )
    return Agent(model, system_prompt=system_prompt, output_type=str)


def _build_agent():
    """Insight agent (the grounded F1-analyst prompt)."""
    return _build_agent_for(_SYSTEM_PROMPT)


async def llm_tip(facts: str, *, allowed_codes: set[str] | None = None) -> str | None:
    """
    Return a one-sentence grounded insight for the given facts, or None.

    Args:
        facts: Plain-text structured facts (already computed deterministically).
        allowed_codes: Driver codes the insight may reference. If the model names
            any other driver, the insight is rejected (fall back to rules) so a
            free model can never surface a hallucinated driver.

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
    if allowed_codes is not None and not _is_grounded(text, allowed_codes):
        logger.info("llm_insight rejected (off-fact driver reference): {!r}", text)
        return None
    return text[:280]
