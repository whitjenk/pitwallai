"""Pydantic AI tool functions for the Radio Intercept Decoder agent."""

from __future__ import annotations

import asyncio

from pydantic_ai import RunContext

from pitwallai.agents.radio_intercept.models import AgentDependencies, HistoricalRadio
from pitwallai.agents.radio_intercept.seed_data import DRIVER_CONTEXT


async def query_historical_context(
    ctx: RunContext[AgentDependencies],
    transcript: str,
    n_results: int = 5,
) -> list[HistoricalRadio]:
    """
    Query the historical radio vector store for semantically similar transmissions.

    Returns ranked results with similarity scores. Use this to ground your decode
    in real precedents before assigning intent and strategic signal.

    Args:
        ctx: Pydantic AI run context with injected dependencies.
        transcript: Live transcript text to search against.
        n_results: Maximum historical documents to retrieve.

    Returns:
        Ranked historical radio records with similarity scores.
    """
    effective_n = min(n_results, ctx.deps.max_context_results)
    return await asyncio.to_thread(
        ctx.deps.vector_store.query,
        transcript,
        effective_n,
    )


async def lookup_jargon(
    ctx: RunContext[AgentDependencies],
    terms: list[str],
) -> dict[str, str]:
    """
    Look up F1 radio jargon terms in the team's reference glossary.

    Pass a list of terms exactly as spoken. Returns a dict of term → plain English.
    Terms not found in the glossary are returned with value 'UNKNOWN'.

    Args:
        ctx: Pydantic AI run context with injected dependencies.
        terms: Jargon terms as spoken on radio.

    Returns:
        Mapping of each requested term to its plain-English meaning or 'UNKNOWN'.
    """
    glossary = {key.lower(): value for key, value in ctx.deps.jargon_glossary.items()}
    results: dict[str, str] = {}
    for term in terms:
        normalized = term.strip().lower()
        results[term] = glossary.get(normalized, "UNKNOWN")
    return results


async def get_driver_context(
    ctx: RunContext[AgentDependencies],
    driver_code: str,
) -> dict:
    """
    Returns static context about a driver relevant to radio decode.

    Includes typical communication style, known jargon preferences, and team
    strategy tendencies. Used to disambiguate intent when transcripts are ambiguous.

    Args:
        ctx: Pydantic AI run context with injected dependencies.
        driver_code: Three-letter driver code (e.g. 'VER').

    Returns:
        Driver context dict, or a minimal default if the driver is not catalogued.
    """
    code = driver_code.strip().upper()
    if code in DRIVER_CONTEXT:
        return DRIVER_CONTEXT[code]
    return {
        "name": f"Driver {code}",
        "team": "Unknown",
        "number": 0,
        "communication_style": "Unknown — use transcript and historical context",
        "known_phrases": [],
        "strategy_tendency": "Unknown — rely on historical precedents",
    }


async def get_team_color(
    ctx: RunContext[AgentDependencies],
    team: str,
) -> str:
    """
    Returns the official hex color code for a given F1 team name.

    Used to populate team_color on DecodedTransmission for dashboard rendering.
    Returns '#FFFFFF' if team not found.

    Args:
        ctx: Pydantic AI run context with injected dependencies.
        team: Full team name as used in radio metadata.

    Returns:
        Hex color string (e.g. '#FF8000').
    """
    return ctx.deps.team_colors.get(team, "#FFFFFF")
