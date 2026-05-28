"""Typed Pydantic models for OpenF1 API responses."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _OpenF1Base(BaseModel):
    """Base model accepting extra OpenF1 fields without failing validation."""

    model_config = ConfigDict(extra="ignore")


class SessionInfo(_OpenF1Base):
    """GET /v1/sessions row."""

    session_key: int
    session_name: str | None = None
    session_type: str | None = None
    meeting_key: int | None = None
    year: int | None = None
    country_name: str | None = None
    circuit_key: int | None = None
    circuit_short_name: str | None = None
    date_start: datetime | None = None
    date_end: datetime | None = None
    location: str | None = None


class LapRecord(_OpenF1Base):
    """GET /v1/laps row."""

    session_key: int
    driver_number: int
    lap_number: int
    lap_duration: float | None = None
    duration_sector_1: float | None = None
    duration_sector_2: float | None = None
    duration_sector_3: float | None = None
    is_pit_out_lap: bool | None = None
    date_start: datetime | None = None


class CarDataSample(_OpenF1Base):
    """GET /v1/car_data row."""

    session_key: int
    driver_number: int
    date: datetime | None = None
    speed: float | None = None
    throttle: float | None = None
    brake: int | None = None
    n_gear: int | None = None
    rpm: int | None = None
    drs: int | None = None


class PositionSample(_OpenF1Base):
    """GET /v1/position row."""

    session_key: int
    driver_number: int
    position: int | None = None
    date: datetime | None = None


class TeamRadioEntry(_OpenF1Base):
    """GET /v1/team_radio row."""

    session_key: int
    driver_number: int
    date: datetime | None = None
    recording_url: str | None = None
    transcript: str | None = None

    @property
    def raw_transcript(self) -> str:
        """Normalized transcript text for the decode pipeline."""
        return (self.transcript or "").strip()


class WeatherSample(_OpenF1Base):
    """GET /v1/weather row."""

    session_key: int
    date: datetime | None = None
    air_temperature: float | None = None
    track_temperature: float | None = None
    humidity: float | None = None
    pressure: float | None = None
    rainfall: bool | None = None
    wind_direction: int | None = None
    wind_speed: float | None = None


class PitStop(_OpenF1Base):
    """GET /v1/pit row."""

    session_key: int
    driver_number: int
    lap_number: int | None = None
    pit_duration: float | None = None
    date: datetime | None = None


class RaceControlMessage(_OpenF1Base):
    """GET /v1/race_control row."""

    session_key: int
    date: datetime | None = None
    category: str | None = None
    message: str | None = None
    scope: str | None = None
    sector: int | None = None
    driver_number: int | None = None
    lap_number: int | None = None
    flag: str | None = None


class SessionResultRow(_OpenF1Base):
    """GET /v1/session_result row (qualifying / race results)."""

    session_key: int
    driver_number: int
    position: int | None = None
    dnf: bool | None = None
    dns: bool | None = None
    dsq: bool | None = None


def parse_list(model: type[BaseModel], payload: list[dict[str, Any]]) -> list[BaseModel]:
    """
    Parse a list of JSON dicts into typed models.

    Args:
        model: Pydantic model class.
        payload: Raw JSON array from OpenF1.

    Returns:
        List of validated model instances.
    """
    return [model.model_validate(row) for row in payload]
