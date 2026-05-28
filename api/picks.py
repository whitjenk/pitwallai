"""REST API for fantasy picks generation."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from intelligence.active_weekend import ActiveWeekend
from intelligence.picks_config import PicksSettings
from intelligence.picks_pipeline import PicksRunResult
from intelligence.schemas import PickOutput

router = APIRouter(prefix="/api/picks", tags=["picks"])


class ActiveWeekendResponse(BaseModel):
    """Serializable active weekend metadata."""

    model_config = ConfigDict(frozen=True)

    circuit_key: str
    display_name: str
    openf1_circuit_name: str
    year: int
    race_key: str
    race_session_key: int | None
    qualifying_session_key: int | None
    race_start: datetime | None


class PicksResponse(BaseModel):
    """API response wrapping the sacred PickOutput schema."""

    model_config = ConfigDict(frozen=True)

    weekend: ActiveWeekendResponse
    output: PickOutput
    generated_at: datetime
    practice_signal_count: int
    cached: bool = Field(
        description="True when served from the last scheduled/cached run without refresh."
    )


def _weekend_response(weekend: ActiveWeekend) -> ActiveWeekendResponse:
    return ActiveWeekendResponse(
        circuit_key=weekend.circuit_key,
        display_name=weekend.display_name,
        openf1_circuit_name=weekend.openf1_circuit_name,
        year=weekend.year,
        race_key=weekend.race_key,
        race_session_key=weekend.race_session_key,
        qualifying_session_key=weekend.qualifying_session_key,
        race_start=weekend.race_start,
    )


def _result_response(result: PicksRunResult, *, cached: bool) -> PicksResponse:
    return PicksResponse(
        weekend=_weekend_response(result.weekend),
        output=result.output,
        generated_at=result.generated_at,
        practice_signal_count=result.practice_signal_count,
        cached=cached,
    )


def _matches_cached(
    cached: PicksRunResult | None,
    *,
    phone: str | None,
    circuit_key: str | None,
    year: int | None,
) -> bool:
    """True when the cached generic run can be served without regeneration."""
    if cached is None or phone is not None:
        return False
    if circuit_key and cached.weekend.circuit_key != circuit_key.strip().lower():
        return False
    if year is not None and cached.weekend.year != year:
        return False
    return True


@router.get("", response_model=PicksResponse)
async def get_picks(
    request: Request,
    phone: str | None = Query(
        default=None,
        description="Subscriber phone (E.164) for personalized PATH A picks.",
    ),
    circuit_key: str | None = Query(
        default=None,
        description="Override circuit (e.g. monaco). Defaults to active weekend.",
    ),
    year: int | None = Query(default=None, ge=2020, le=2035),
    refresh: bool = Query(
        default=False,
        description="Force a new OpenF1 fetch and regeneration.",
    ),
) -> PicksResponse:
    """
    Return fantasy picks for the active (or specified) race weekend.

    Without ``refresh``, returns the last cached result when parameters match.
    """
    scheduler = request.app.state.picks_scheduler
    cached: PicksRunResult | None = getattr(request.app.state, "last_picks_result", None)

    if not refresh and _matches_cached(cached, phone=phone, circuit_key=circuit_key, year=year):
        assert cached is not None
        return _result_response(cached, cached=True)

    try:
        result = await scheduler.run_once(
            phone=phone,
            circuit_key=circuit_key,
            year=year,
            persist_picks=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Picks pipeline failed: {exc}") from exc

    if result is None:
        raise HTTPException(status_code=409, detail="Picks pipeline already running")

    return _result_response(result, cached=False)


@router.post("/generate", response_model=PicksResponse)
async def generate_picks(
    request: Request,
    phone: str | None = Query(default=None),
    circuit_key: str | None = Query(default=None),
    year: int | None = Query(default=None, ge=2020, le=2035),
) -> PicksResponse:
    """
    Trigger an immediate picks pipeline run (same as GET with refresh=true).
    """
    scheduler = request.app.state.picks_scheduler
    try:
        result = await scheduler.run_once(
            phone=phone,
            circuit_key=circuit_key,
            year=year,
            persist_picks=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Picks pipeline failed: {exc}") from exc

    if result is None:
        raise HTTPException(status_code=409, detail="Picks pipeline already running")

    return _result_response(result, cached=False)


@router.get("/status")
async def picks_status(request: Request) -> dict[str, Any]:
    """
    Return picks scheduler status and last run metadata.
    """
    settings: PicksSettings = request.app.state.picks_settings
    cached: PicksRunResult | None = getattr(request.app.state, "last_picks_result", None)
    payload: dict[str, Any] = {
        "auto_enabled": settings.auto_enabled,
        "interval_seconds": settings.interval_seconds,
        "race_year": settings.race_year,
        "circuit_key_override": settings.circuit_key_override,
        "last_run": None,
    }
    if cached is not None:
        payload["last_run"] = {
            "generated_at": cached.generated_at.isoformat(),
            "circuit_key": cached.weekend.circuit_key,
            "race_key": cached.weekend.race_key,
            "practice_signal_count": cached.practice_signal_count,
            "personalized": cached.output.personalized,
            "pick_count": len(cached.output.picks),
        }
    return payload
