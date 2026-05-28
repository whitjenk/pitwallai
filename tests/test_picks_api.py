"""Tests for picks API and active weekend resolution."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.server import create_app
from intelligence.active_weekend import resolve_active_weekend
from intelligence.context import init_orchestrator_context
from intelligence.picks_config import PicksSettings
from intelligence.picks_pipeline import PicksRunResult
from intelligence.schemas import PickOutput, PickRecommendation
from openf1.models import SessionInfo


@pytest.fixture
def picks_app() -> TestClient:
    """Test client with picks scheduler disabled (no background OpenF1)."""
    app = create_app(mode="rehearsal", settings=None)
    app.state.picks_settings = PicksSettings(
        auto_enabled=False,
        interval_seconds=1800,
        race_year=2026,
        circuit_key_override="monaco",
        api_key="test-api-key",
    )
    app.state.picks_scheduler = MagicMock()
    app.state.picks_scheduler.run_once = AsyncMock(return_value=None)
    return TestClient(app)


def test_picks_status_endpoint(picks_app: TestClient) -> None:
    response = picks_app.get(
        "/api/picks/status",
        headers={"X-PitWall-API-Key": "test-api-key"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["auto_enabled"] is False
    assert body["circuit_key_override"] == "monaco"


@pytest.mark.asyncio
async def test_resolve_active_weekend_override() -> None:
    ctx = init_orchestrator_context()
    client = AsyncMock()
    client.find_session_key = AsyncMock(return_value=999)
    client.get_sessions = AsyncMock(
        return_value=[
            SessionInfo(
                session_key=999,
                session_name="Race",
                meeting_key=1,
                circuit_short_name="Monaco",
                date_start=datetime.now(tz=UTC) + timedelta(days=2),
            )
        ]
    )

    weekend = await resolve_active_weekend(
        client,
        ctx,
        year=2026,
        circuit_key_override="monaco",
    )
    assert weekend.circuit_key == "monaco"
    assert weekend.race_session_key == 999


def test_get_picks_returns_cached(picks_app: TestClient) -> None:
    from circuits.profiles import get_circuit_profile
    from intelligence.active_weekend import ActiveWeekend

    monaco = get_circuit_profile("monaco")
    assert monaco is not None

    cached = PicksRunResult(
        output=PickOutput(
            picks=[
                PickRecommendation(
                    rank=1,
                    headline="Target NOR",
                    confidence=72.0,
                    reasoning="test",
                    driver_code="NOR",
                )
            ],
            personalized=False,
            circuit_note="Monaco",
            confidence_note="test",
            generated_by="rules",
        ),
        weekend=ActiveWeekend(
            circuit_key="monaco",
            display_name="Monaco",
            openf1_circuit_name="Monaco",
            year=2026,
            race_session_key=1,
            qualifying_session_key=2,
            meeting_key=1,
            race_start=None,
        ),
        circuit=monaco,
        generated_at=datetime.now(tz=UTC),
        practice_signal_count=0,
    )
    picks_app.app.state.last_picks_result = cached

    response = picks_app.get(
        "/api/picks",
        headers={"X-PitWall-API-Key": "test-api-key"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["cached"] is True
    assert body["output"]["picks"][0]["driver_code"] == "NOR"


def test_personalized_picks_requires_api_key(picks_app: TestClient) -> None:
    response = picks_app.get("/api/picks", params={"phone": "+15551234567"})
    assert response.status_code == 401


def test_refresh_picks_requires_api_key(picks_app: TestClient) -> None:
    response = picks_app.get("/api/picks", params={"refresh": "true"})
    assert response.status_code == 401


def test_generate_picks_requires_api_key(picks_app: TestClient) -> None:
    response = picks_app.post("/api/picks/generate")
    assert response.status_code == 401


def test_picks_require_server_key_config(picks_app: TestClient) -> None:
    picks_app.app.state.picks_settings = PicksSettings(
        auto_enabled=False,
        interval_seconds=1800,
        race_year=2026,
        circuit_key_override="monaco",
        api_key="",
    )
    response = picks_app.get("/api/picks", headers={"X-PitWall-API-Key": "anything"})
    assert response.status_code == 503


def test_season_recap_invalid_token_returns_404(picks_app: TestClient) -> None:
    response = picks_app.get("/api/season/not-a-valid-token")
    assert response.status_code == 404


def test_season_share_page_invalid_token_returns_404(picks_app: TestClient) -> None:
    response = picks_app.get("/you/not-a-valid-token")
    assert response.status_code == 404


def test_season_share_page_renders_html(picks_app: TestClient) -> None:
    with patch("api.server.parse_share_token", return_value=("+15551234567", 2026)):
        with patch(
            "api.server.build_season_recap",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    season=2026,
                    personalized_accuracy_pct=61.0,
                    community_accuracy_pct=58.0,
                    best_call="ALB at Monaco (+12 pts)",
                    worst_call="SAI at Silverstone (-9 pts)",
                    biggest_signal="practice sentiment was 71% predictive",
                    share_url="https://pitwallai.app/you/mock",
                )
            ),
        ):
            with patch("api.server.build_latest_session_snapshot", new=AsyncMock(return_value=None)):
                response = picks_app.get("/you/mock.token")
    assert response.status_code == 200
    assert "Season complete" in response.text
    assert "ALB at Monaco" in response.text
    assert 'property="og:title"' in response.text
    assert 'name="twitter:card"' in response.text
    assert 'data-trend="up"' in response.text or 'data-trend="flat"' in response.text
    assert "trend-pill" in response.text
    assert "aria-label" in response.text
