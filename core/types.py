"""Public data types for the core fantasy API.

Two small, platform-neutral models the Slack app passes in and brief 005 stores
unchanged. Deliberately minimal — just what a fantasy team and a race-week
lineup are, with no database or chat-platform concepts attached.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Team(BaseModel):
    """A player's standing fantasy squad and chip/budget state."""

    model_config = ConfigDict(frozen=True)

    drivers: list[str] = Field(default_factory=list)
    constructors: list[str] = Field(default_factory=list)
    budget_m: float = 0.0
    transfers_available: int = 0
    chips_used: dict[str, bool] = Field(default_factory=dict)


class Lineup(BaseModel):
    """A lineup stated for one race: drivers, constructors, chip and captain."""

    model_config = ConfigDict(frozen=True)

    drivers: list[str] = Field(default_factory=list)
    constructors: list[str] = Field(default_factory=list)
    chip: str | None = None
    captain: str | None = None
