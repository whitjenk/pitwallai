"""Async OpenF1 REST client with rate limiting and Postgres cache."""

from __future__ import annotations

import asyncio
import time
from typing import Any, TypeVar

import httpx
from loguru import logger
from pydantic import BaseModel

from openf1.cache import CacheTier, cache_get, cache_key_for, cache_set
from openf1.models import (
    CarDataSample,
    LapRecord,
    PitStop,
    PositionSample,
    SessionInfo,
    RaceControlMessage,
    SessionResultRow,
    TeamRadioEntry,
    WeatherSample,
    parse_list,
)

T = TypeVar("T", bound=BaseModel)

_BASE_URL = "https://api.openf1.org/v1"
_MIN_INTERVAL_S = 0.25  # 4 requests per second max


class OpenF1Client:
    """
    Rate-limited async client for OpenF1.

    All fetch methods return typed Pydantic models. Responses are cached in
    Postgres with tier-appropriate TTLs.
    """

    def __init__(self, *, timeout_s: float = 30.0) -> None:
        """
        Initialize the client.

        Args:
            timeout_s: HTTP request timeout in seconds.
        """
        self._timeout = timeout_s
        self._lock = asyncio.Lock()
        self._last_request_at = 0.0

    async def _throttle(self) -> None:
        """Enforce 4 req/s global rate limit."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request_at
            if elapsed < _MIN_INTERVAL_S:
                await asyncio.sleep(_MIN_INTERVAL_S - elapsed)
            self._last_request_at = time.monotonic()

    async def _fetch_raw(
        self,
        endpoint: str,
        params: dict[str, Any],
        *,
        tier: CacheTier,
    ) -> list[dict[str, Any]]:
        """
        Fetch JSON array from OpenF1 with cache and rate limit.

        Args:
            endpoint: Endpoint path without /v1/ prefix (e.g. 'laps').
            params: Query parameters.
            tier: Cache TTL tier.

        Returns:
            List of JSON objects.
        """
        key = cache_key_for(endpoint, params)
        cached = await cache_get(key)
        if cached is not None:
            logger.debug("OpenF1 cache hit endpoint={} params={}", endpoint, params)
            return cached

        await self._throttle()
        url = f"{_BASE_URL}/{endpoint}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, list):
                raise ValueError(f"OpenF1 {endpoint} returned non-list payload")
        await cache_set(key, endpoint, tier, data)
        logger.debug("OpenF1 fetched endpoint={} rows={}", endpoint, len(data))
        return data

    async def _fetch_typed(
        self,
        endpoint: str,
        params: dict[str, Any],
        model: type[T],
        *,
        tier: CacheTier,
    ) -> list[T]:
        """Fetch and parse into a list of Pydantic models."""
        raw = await self._fetch_raw(endpoint, params, tier=tier)
        return parse_list(model, raw)  # type: ignore[return-value]

    async def get_sessions(
        self,
        *,
        year: int | None = None,
        country_name: str | None = None,
        circuit_short_name: str | None = None,
        session_name: str | None = None,
        session_type: str | None = None,
        meeting_key: int | None = None,
    ) -> list[SessionInfo]:
        """
        Find sessions by year, circuit, and session type.

        Args:
            year: Championship year.
            country_name: Host country.
            circuit_short_name: Circuit short name (e.g. Monaco).
            session_name: Session label (Practice 1, Qualifying, Race).
            session_type: OpenF1 session type filter.
            meeting_key: Meeting identifier.

        Returns:
            Matching SessionInfo rows.
        """
        params: dict[str, Any] = {}
        if year is not None:
            params["year"] = year
        if country_name is not None:
            params["country_name"] = country_name
        if circuit_short_name is not None:
            params["circuit_short_name"] = circuit_short_name
        if session_name is not None:
            params["session_name"] = session_name
        if session_type is not None:
            params["session_type"] = session_type
        if meeting_key is not None:
            params["meeting_key"] = meeting_key
        return await self._fetch_typed("sessions", params, SessionInfo, tier=CacheTier.SESSION)

    async def find_session_key(
        self,
        *,
        year: int,
        circuit_short_name: str,
        session_name: str,
    ) -> int | None:
        """
        Resolve session_key for a year + circuit + session name.

        Args:
            year: Championship year.
            circuit_short_name: Circuit short name.
            session_name: e.g. 'Practice 1', 'Qualifying', 'Race'.

        Returns:
            session_key or None.
        """
        sessions = await self.get_sessions(
            year=year,
            circuit_short_name=circuit_short_name,
            session_name=session_name,
        )
        if not sessions:
            return None
        return sessions[0].session_key

    async def get_laps(
        self,
        session_key: int,
        *,
        driver_number: int | None = None,
        lap_number: int | None = None,
    ) -> list[LapRecord]:
        """Fetch lap times for a session."""
        params: dict[str, Any] = {"session_key": session_key}
        if driver_number is not None:
            params["driver_number"] = driver_number
        if lap_number is not None:
            params["lap_number"] = lap_number
        return await self._fetch_typed("laps", params, LapRecord, tier=CacheTier.LAP)

    async def get_car_data(
        self,
        session_key: int,
        *,
        driver_number: int | None = None,
    ) -> list[CarDataSample]:
        """Fetch car telemetry samples."""
        params: dict[str, Any] = {"session_key": session_key}
        if driver_number is not None:
            params["driver_number"] = driver_number
        return await self._fetch_typed("car_data", params, CarDataSample, tier=CacheTier.LIVE)

    async def get_positions(
        self,
        session_key: int,
        *,
        driver_number: int | None = None,
    ) -> list[PositionSample]:
        """Fetch position samples."""
        params: dict[str, Any] = {"session_key": session_key}
        if driver_number is not None:
            params["driver_number"] = driver_number
        return await self._fetch_typed("position", params, PositionSample, tier=CacheTier.LIVE)

    async def get_team_radio(
        self,
        session_key: int,
        *,
        driver_number: int | None = None,
    ) -> list[TeamRadioEntry]:
        """Fetch team radio transcript entries."""
        params: dict[str, Any] = {"session_key": session_key}
        if driver_number is not None:
            params["driver_number"] = driver_number
        return await self._fetch_typed("team_radio", params, TeamRadioEntry, tier=CacheTier.LAP)

    async def get_weather(self, session_key: int) -> list[WeatherSample]:
        """Fetch weather samples for a session."""
        params: dict[str, Any] = {"session_key": session_key}
        return await self._fetch_typed("weather", params, WeatherSample, tier=CacheTier.LIVE)

    async def get_pit_stops(
        self,
        session_key: int,
        *,
        driver_number: int | None = None,
    ) -> list[PitStop]:
        """Fetch pit stop entries."""
        params: dict[str, Any] = {"session_key": session_key}
        if driver_number is not None:
            params["driver_number"] = driver_number
        return await self._fetch_typed("pit", params, PitStop, tier=CacheTier.LAP)

    async def get_race_control(self, session_key: int) -> list[RaceControlMessage]:
        """Fetch race control messages for a session."""
        params: dict[str, Any] = {"session_key": session_key}
        return await self._fetch_typed(
            "race_control",
            params,
            RaceControlMessage,
            tier=CacheTier.LIVE,
        )

    async def get_session_results(self, session_key: int) -> list[SessionResultRow]:
        """Fetch session results (qualifying grid / race classification)."""
        params: dict[str, Any] = {"session_key": session_key}
        return await self._fetch_typed(
            "session_result",
            params,
            SessionResultRow,
            tier=CacheTier.LAP,
        )
