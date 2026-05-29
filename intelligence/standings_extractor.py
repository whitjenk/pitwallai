"""Extract a user's mini-league standings from a screenshot.

Mirror of team_extractor — single Gemini Vision call, structured output,
graceful failure. Feeds the Monday league post-mortem broadcast.
"""

from __future__ import annotations

import os
from typing import Literal

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator


class StandingsEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    position: int | None = Field(default=None, description="1 = leader.")
    user_name: str | None = Field(default=None, description="As shown in the app.")
    points: int | None = Field(default=None, description="Season total points.")
    is_user: bool = Field(default=False, description="True for the subscriber themselves.")


class LeagueStandings(BaseModel):
    model_config = ConfigDict(frozen=True)

    league_name: str | None = None
    entries: list[StandingsEntry] = Field(default_factory=list)
    overall_confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    not_a_standings_screen: bool = False

    @field_validator("entries", mode="before")
    @classmethod
    def _trim(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        return value[:50]  # mini-leagues are small; cap to avoid runaway


StandingsStatus = Literal["ok", "rejected", "error"]


class StandingsExtractionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: StandingsStatus
    standings: LeagueStandings | None = None
    error_message: str = ""


_SYSTEM_PROMPT = """You read F1 Fantasy mini-league standings screenshots.

Return one entry per row visible. Position is the rank (1 = leader).
Mark is_user=true for the row that the subscriber highlighted (often shown
in a different colour, with "YOU", or bolded).

If the image isn't a league standings screen, set not_a_standings_screen=true
and return an empty entries list.

Set overall_confidence honestly — if names are blurry or positions ambiguous,
lower the score so the caller can drop the result.
"""


async def _build_agent():
    from pydantic_ai import Agent

    from pitwallai.agents.radio_intercept.model_factory import get_model, resolve_api_key

    provider = os.getenv("PITWALL_LLM_PROVIDER", "gemini").strip().lower() or "gemini"
    model_name = os.getenv("PITWALL_LLM_MODEL", "").strip() or None
    use_vertex = os.getenv("PITWALL_LLM_USE_VERTEX", "false").strip().lower() in {"1", "true", "yes"}

    model = get_model(
        provider=provider,
        api_key=resolve_api_key(provider),
        model_name=model_name,
        use_vertex=use_vertex,
    )
    return Agent(model, output_type=LeagueStandings, system_prompt=_SYSTEM_PROMPT)


async def extract_standings_from_image(
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
) -> StandingsExtractionResult:
    if not image_bytes:
        return StandingsExtractionResult(status="error", error_message="empty image")

    try:
        from pydantic_ai import BinaryContent

        agent = await _build_agent()
        run = await agent.run([
            "Extract the league standings from this F1 Fantasy screenshot.",
            BinaryContent(data=image_bytes, media_type=mime_type),
        ])
        standings: LeagueStandings = run.output
    except Exception as exc:  # pragma: no cover
        logger.exception("standings_extractor: vision call failed: {}", exc)
        return StandingsExtractionResult(status="error", error_message=str(exc))

    if standings.not_a_standings_screen or standings.overall_confidence < 0.3:
        return StandingsExtractionResult(status="rejected", standings=standings)

    return StandingsExtractionResult(status="ok", standings=standings)
