"""Store-local Pydantic models.

Field names mirror ``core.types`` (brief 004) so converting is a one-liner,
but ``store/`` deliberately does not import ``core/``.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class Team(BaseModel):
    """A league-mate's fantasy team, keyed by their Slack user id."""

    slack_user_id: str
    slack_team_id: str
    display_name: str
    drivers: list[str] = Field(default_factory=list)
    constructors: list[str] = Field(default_factory=list)
    budget_m: float = 0.0
    transfers_available: int = 0
    chips_used: dict[str, bool] = Field(default_factory=dict)
    updated_at: datetime | None = None


class LockedLineup(BaseModel):
    """A lineup a user locked in for one race. Re-locking replaces it."""

    slack_user_id: str
    race_key: str
    drivers: list[str] = Field(default_factory=list)
    constructors: list[str] = Field(default_factory=list)
    chip: str | None = None
    captain: str | None = None
    model_lineup: dict | None = None
    locked_at: datetime | None = None
