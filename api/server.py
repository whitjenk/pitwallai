"""FastAPI bridge between the radio intercept pipeline and the React dashboard."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from loguru import logger
from pydantic import BaseModel

from api.picks import router as picks_router
from intelligence.season_recap import (
    build_latest_session_snapshot,
    build_season_recap,
    parse_share_token,
)
from intelligence.share_page import render_season_share_html
from openf1.client import OpenF1Client
from api.rehearsal import SCENARIOS, RehearsalEngine
from pitwallai.agents.radio_intercept.agent import RadioInterceptAgent
from pitwallai.agents.radio_intercept.config import PitWallSettings
from pitwallai.agents.radio_intercept.decode_utils import is_valid_transmission_id
from pitwallai.agents.radio_intercept.enums import (
    ConfirmationState,
    StreamEventType,
    UrgencyLevel,
)
from pitwallai.agents.radio_intercept.models import (
    DecodedTransmission,
    WebSocketEvent,
)
from pitwallai.agents.radio_intercept.seed_data import (
    JARGON_GLOSSARY,
    MONACO_REHEARSAL_SCENARIO,
    TEAM_COLORS,
)
from pitwallai.agents.radio_intercept.stream_handler import RadioInterceptDecoder
from pitwallai.agents.radio_intercept.vector_store import MockVectorStore

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_PATH = PROJECT_ROOT / "dashboard.jsx"


class ConfirmIntelBody(BaseModel):
    """Request body for competitor intel confirmation."""

    state: ConfirmationState


class RehearsalStartBody(BaseModel):
    """Request body to start a rehearsal scenario."""

    scenario: str = "monaco_2024"


@dataclass
class SessionState:
    """
    In-memory session state for API queries and dashboard status.

    Attributes:
        mode: Operating mode ('live' or 'rehearsal').
        session_key: Active OpenF1 or rehearsal session key.
        circuit: Human-readable circuit name.
        transmissions: Decoded transmissions keyed by transmission_id.
        active_drivers: Driver codes heard this session.
        current_lap: Latest lap number observed.
    """

    mode: str = "rehearsal"
    session_key: int = 0
    circuit: str = "Unknown"
    transmissions: dict[str, DecodedTransmission] = field(default_factory=dict)
    active_drivers: set[str] = field(default_factory=set)
    current_lap: int = 0


def _urgency_meets_minimum(level: UrgencyLevel, minimum: str | None) -> bool:
    """
    Check whether an urgency level meets a minimum filter string.

    Args:
        level: Transmission urgency level.
        minimum: Minimum urgency name or None for no filter.

    Returns:
        True if the transmission passes the filter.
    """
    if minimum is None:
        return True
    try:
        min_level = UrgencyLevel(minimum.upper())
    except ValueError:
        return True
    return level.priority >= min_level.priority


def create_app(
    mode: str = "rehearsal",
    rehearsal_speed: float = 3.0,
    settings: PitWallSettings | None = None,
) -> FastAPI:
    """
    Create and configure the PitWallAI FastAPI application.

    Args:
        mode: Operating mode ('live' or 'rehearsal').
        rehearsal_speed: Default rehearsal playback speed multiplier.

    Returns:
        Configured FastAPI instance.
    """
    pitwall_settings = settings or PitWallSettings.from_env()

    app = FastAPI(title="PitWallAI Radio Intercept Decoder", version="1.0")
    app.include_router(picks_router)
    app.state.mode = mode
    app.state.rehearsal_speed = rehearsal_speed
    app.state.settings = pitwall_settings
    app.state.session = SessionState(mode=mode)
    app.state.rehearsal_engine = None
    app.state.pipeline_tasks: list[asyncio.Task[Any]] = []
    app.state.ws_connections = 0

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(pitwall_settings.cors_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    def _season_share_secret() -> str:
        from whatsapp.settings import get_whatsapp_settings

        wa_settings = get_whatsapp_settings()
        if wa_settings.whatsapp_app_secret.strip():
            return wa_settings.whatsapp_app_secret.strip()
        if wa_settings.webhook_verify_token.strip():
            return wa_settings.webhook_verify_token.strip()
        return "pitwallai-season-share-local-secret"

    @app.on_event("startup")
    async def on_startup() -> None:
        """
        Initialize pipeline components and start background tasks.

        Starts decoder consumer/emitter, optional live WebSocket producer,
        session collector, and auto-starts Monaco rehearsal in rehearsal mode.
        """
        log = logger.bind(mode=mode)
        log.info("Initializing PitWallAI components")

        from intelligence.context import init_orchestrator_context

        app.state.orchestrator_context = init_orchestrator_context()
        app.state.last_picks_result = None

        from db.session import init_db
        from intelligence.price_history import seed_price_history
        from intelligence.picks_config import PicksSettings
        from intelligence.picks_scheduler import PicksScheduler
        from scheduler.runtime import start_race_scheduler, stop_race_scheduler
        from whatsapp.settings import get_whatsapp_settings

        await init_db()
        await seed_price_history()
        picks_settings = PicksSettings.from_env(mode=mode)
        app.state.picks_settings = picks_settings
        app.state.picks_scheduler = PicksScheduler(app, picks_settings)
        if picks_settings.auto_enabled:
            app.state.picks_scheduler.start()
            log.info(
                "Picks poll enabled (every {}s) — quali broadcast uses race scheduler",
                picks_settings.interval_seconds,
            )

        wa_settings = get_whatsapp_settings()
        app.state.race_scheduler = start_race_scheduler(app, wa_settings.database_url)

        vector_store = MockVectorStore(
            embedding_cache_size=pitwall_settings.embedding_cache_size,
        )
        agent = RadioInterceptAgent(settings=pitwall_settings)
        decoder = RadioInterceptDecoder(agent=agent, vector_store=vector_store)
        decoder._running = True

        app.state.vector_store = vector_store
        app.state.agent = agent
        app.state.decoder = decoder
        log.bind(
            decode_backend=pitwall_settings.decode_backend.value,
            llm_enabled=pitwall_settings.llm_enabled,
        ).info("Decode pipeline configured")

        session: SessionState = app.state.session
        if mode == "rehearsal":
            session.circuit = MONACO_REHEARSAL_SCENARIO.circuit
            session.session_key = MONACO_REHEARSAL_SCENARIO.events[0].session_key
            decoder._deps.session_key = session.session_key

        collector_queue: asyncio.Queue[WebSocketEvent] = asyncio.Queue(maxsize=500)
        decoder.subscribe(collector_queue)

        async def session_collector() -> None:
            while decoder._running:
                try:
                    event = await asyncio.wait_for(collector_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                await _handle_session_event(app, event)

        tasks: list[asyncio.Task[Any]] = [
            asyncio.create_task(decoder._agent_consumer()),
            asyncio.create_task(decoder._output_emitter()),
            asyncio.create_task(session_collector()),
        ]
        if mode == "live":
            tasks.append(asyncio.create_task(decoder._ws_producer()))

        app.state.pipeline_tasks = tasks
        app.state.collector_queue = collector_queue

        if mode == "rehearsal":
            engine = RehearsalEngine(decoder, MONACO_REHEARSAL_SCENARIO)
            app.state.rehearsal_engine = engine
            engine.start_background(speed_multiplier=rehearsal_speed)
            log.info("Monaco 2024 rehearsal auto-started")

        from agents.race_monitor import resume_monitors_on_startup
        from agents.base import AgentRunDependencies

        monitor_deps = AgentRunDependencies(
            openf1_client=OpenF1Client(),
            radio_agent=agent,
            vector_store=vector_store,
            settings=pitwall_settings,
        )
        await resume_monitors_on_startup(monitor_deps)

        log.info("PitWallAI startup complete")

    @app.on_event("shutdown")
    async def on_shutdown() -> None:
        """Stop decoder pipeline and cancel background tasks."""
        from scheduler.runtime import stop_race_scheduler

        await stop_race_scheduler()
        picks_sched = getattr(app.state, "picks_scheduler", None)
        if picks_sched is not None:
            await picks_sched.stop()
        decoder: RadioInterceptDecoder = app.state.decoder
        await decoder.stop()
        for task in app.state.pipeline_tasks:
            task.cancel()
        engine: RehearsalEngine | None = app.state.rehearsal_engine
        if engine is not None:
            await engine.stop()

    @app.get("/health")
    async def health() -> dict[str, Any]:
        """
        Health check endpoint.

        Returns:
            Status payload with mode and session key.
        """
        session: SessionState = app.state.session
        pitwall_settings: PitWallSettings = app.state.settings
        agent: RadioInterceptAgent = app.state.agent
        budget_snap = await agent.budget_guard.snapshot(session.session_key)
        return {
            "status": "ok",
            "mode": app.state.mode,
            "session_key": session.session_key,
            "decode_backend": pitwall_settings.decode_backend.value,
            "llm_configured": pitwall_settings.llm_enabled,
            "llm_model": pitwall_settings.llm_model or None,
            "llm_budget_acknowledged": pitwall_settings.llm_budget_acknowledged,
            "llm_budget": agent.budget_guard.to_public_dict(budget_snap),
        }

    @app.get("/api/budget")
    async def budget_status(
        session_key: int | None = Query(default=None),
    ) -> dict[str, Any]:
        """
        Return LLM budget utilization and configured caps.

        Args:
            session_key: Optional session to scope per-session counters.

        Returns:
            Budget snapshot and limits.
        """
        agent: RadioInterceptAgent = app.state.agent
        key = session_key if session_key is not None else app.state.session.session_key
        snap = await agent.budget_guard.snapshot(key)
        return agent.budget_guard.to_public_dict(snap)

    @app.get("/api/season/{token}")
    async def season_recap(token: str) -> dict[str, Any]:
        """Return a public share payload for a season recap token."""
        parsed = parse_share_token(token, _season_share_secret())
        if parsed is None:
            raise HTTPException(status_code=404, detail="Invalid season recap token")
        phone, season = parsed
        recap = await build_season_recap(
            phone=phone,
            season=season,
            share_base_url="https://pitwallai.app",
            share_secret=_season_share_secret(),
        )
        return {
            "season": recap.season,
            "personalized_accuracy_pct": recap.personalized_accuracy_pct,
            "community_accuracy_pct": recap.community_accuracy_pct,
            "best_call": recap.best_call,
            "worst_call": recap.worst_call,
            "biggest_signal": recap.biggest_signal,
            "share_url": recap.share_url,
        }

    @app.get("/you/{token}", response_class=HTMLResponse)
    async def season_recap_page(token: str) -> HTMLResponse:
        """Render a public, share-friendly season recap page."""
        parsed = parse_share_token(token, _season_share_secret())
        if parsed is None:
            raise HTTPException(status_code=404, detail="Invalid season recap token")
        phone, season = parsed
        recap = await build_season_recap(
            phone=phone,
            season=season,
            share_base_url="https://pitwallai.app",
            share_secret=_season_share_secret(),
        )
        session = await build_latest_session_snapshot(phone, season)
        title = f"PitWallAI {recap.season} Season Recap"
        description = (
            f"GP pick hit rate {recap.personalized_accuracy_pct:.0f}% vs community "
            f"{recap.community_accuracy_pct:.0f}% (race results) — best call: {recap.best_call}"
        )
        html = render_season_share_html(
            recap,
            session=session,
            page_title=title,
            meta_description=description,
        )
        return HTMLResponse(content=html)

    @app.get("/dashboard")
    async def dashboard() -> FileResponse:
        """
        Serve the embedded React dashboard.

        Returns:
            FileResponse for dashboard.jsx.

        Raises:
            HTTPException: If dashboard.jsx is missing.
        """
        if not DASHBOARD_PATH.is_file():
            raise HTTPException(status_code=404, detail="dashboard.jsx not found")
        return FileResponse(DASHBOARD_PATH, media_type="text/html")

    @app.get("/api/session/status")
    async def session_status() -> dict[str, Any]:
        """
        Return current session status for the dashboard.

        Returns:
            Mode, lap, drivers, transmission count, and average latency.
        """
        session: SessionState = app.state.session
        transmissions = list(session.transmissions.values())
        recent = transmissions[-10:]
        latencies = [
            t.processing_latency_ms
            for t in recent
            if t.processing_latency_ms is not None
        ]
        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
        engine: RehearsalEngine | None = app.state.rehearsal_engine
        progress = engine.get_progress() if engine is not None else {}
        return {
            "mode": session.mode,
            "current_lap": session.current_lap or progress.get("current_lap", 0),
            "circuit": session.circuit,
            "session_key": session.session_key,
            "active_drivers": sorted(session.active_drivers),
            "transmission_count": len(session.transmissions),
            "avg_latency_ms": round(avg_latency, 1),
            "rehearsal_progress": progress,
        }

    @app.post("/api/intel/confirm/{transmission_id}")
    async def confirm_intel(
        transmission_id: str,
        body: ConfirmIntelBody,
    ) -> DecodedTransmission:
        """
        Update competitor intel confirmation state for a transmission.

        Args:
            transmission_id: Unique transmission identifier.
            body: Confirmation state payload.

        Returns:
            Updated DecodedTransmission.

        Raises:
            HTTPException: If transmission or intel is not found.
        """
        if not is_valid_transmission_id(transmission_id):
            raise HTTPException(status_code=400, detail="Invalid transmission_id format")
        if body.state not in (
            ConfirmationState.ACKNOWLEDGED,
            ConfirmationState.ACTED_ON,
        ):
            raise HTTPException(status_code=400, detail="Invalid confirmation state")

        session: SessionState = app.state.session
        transmission = session.transmissions.get(transmission_id)
        if transmission is None:
            raise HTTPException(status_code=404, detail="Transmission not found")
        if transmission.competitor_intel is None:
            raise HTTPException(status_code=404, detail="No competitor intel on transmission")

        updated_intel = transmission.competitor_intel.model_copy(
            update={"confirmation_state": body.state}
        )
        updated = transmission.model_copy(update={"competitor_intel": updated_intel})
        session.transmissions[transmission_id] = updated
        return updated

    @app.post("/api/rehearsal/start")
    async def rehearsal_start(body: RehearsalStartBody) -> dict[str, Any]:
        """
        Start or restart a rehearsal scenario.

        Args:
            body: Scenario selection payload.

        Returns:
            Started status with event count and estimated duration.

        Raises:
            HTTPException: If scenario name is unknown.
        """
        scenario = SCENARIOS.get(body.scenario)
        if scenario is None:
            raise HTTPException(status_code=404, detail=f"Unknown scenario: {body.scenario}")

        decoder: RadioInterceptDecoder = app.state.decoder
        engine: RehearsalEngine | None = app.state.rehearsal_engine
        if engine is not None:
            await engine.stop()

        speed = app.state.rehearsal_speed
        engine = RehearsalEngine(decoder, scenario)
        app.state.rehearsal_engine = engine
        engine.start_background(speed_multiplier=speed)

        session: SessionState = app.state.session
        session.circuit = scenario.circuit
        session.session_key = scenario.events[0].session_key if scenario.events else 0
        session.mode = "rehearsal"
        decoder._deps.session_key = session.session_key

        return {
            "status": "started",
            "total_events": len(scenario.events),
            "estimated_duration_seconds": RehearsalEngine.estimate_duration_seconds(
                scenario, speed
            ),
        }

    @app.post("/api/rehearsal/stop")
    async def rehearsal_stop() -> dict[str, str]:
        """
        Cancel the active rehearsal run.

        Returns:
            Stopped status dict.
        """
        engine: RehearsalEngine | None = app.state.rehearsal_engine
        if engine is not None:
            await engine.stop()
        return {"status": "stopped"}

    @app.get("/api/history")
    async def history(
        limit: int = Query(default=50, ge=1, le=500),
        driver_code: str | None = Query(default=None),
        min_urgency: str | None = Query(default=None),
    ) -> list[dict[str, Any]]:
        """
        Return filtered session transmission history.

        Args:
            limit: Maximum records to return.
            driver_code: Optional driver code filter.
            min_urgency: Optional minimum urgency filter.

        Returns:
            List of serialized DecodedTransmission dicts, newest first.
        """
        session: SessionState = app.state.session
        items = list(session.transmissions.values())
        items.sort(key=lambda t: t.timestamp, reverse=True)

        filtered: list[DecodedTransmission] = []
        for item in items:
            if driver_code and item.driver_code.upper() != driver_code.upper():
                continue
            if not _urgency_meets_minimum(item.urgency_level, min_urgency):
                continue
            filtered.append(item)

        return [t.model_dump(mode="json") for t in filtered[:limit]]

    @app.websocket("/ws/stream")
    async def ws_stream(websocket: WebSocket) -> None:
        """
        WebSocket stream of real-time PitWallAI events.

        Subscribes to decoder fan-out and forwards JSON-serialized WebSocketEvent messages.

        Args:
            websocket: Connected WebSocket client.
        """
        pitwall_settings: PitWallSettings = app.state.settings
        if app.state.ws_connections >= pitwall_settings.ws_max_connections:
            await websocket.close(code=1008, reason="Too many connections")
            return

        await websocket.accept()
        app.state.ws_connections += 1
        decoder: RadioInterceptDecoder = app.state.decoder
        queue: asyncio.Queue[WebSocketEvent] = asyncio.Queue(maxsize=100)
        decoder.subscribe(queue)

        status_event = await _build_system_status(app)
        await websocket.send_text(status_event.model_dump_json())

        try:
            while True:
                event = await queue.get()
                payload = event.model_dump_json()
                if len(payload) > 256_000:
                    continue
                await websocket.send_text(payload)
        except WebSocketDisconnect:
            logger.info("WebSocket client disconnected")
        finally:
            decoder.unsubscribe(queue)
            app.state.ws_connections = max(0, app.state.ws_connections - 1)

    return app


async def _handle_session_event(app: FastAPI, event: WebSocketEvent) -> None:
    """
    Update session state from a streamed WebSocket event.

    Args:
        app: FastAPI application with session state.
        event: Incoming WebSocket event.
    """
    session: SessionState = app.state.session
    if event.event_type == StreamEventType.TRANSMISSION_DECODED:
        if not isinstance(event.payload, DecodedTransmission):
            return
        transmission = event.payload
        if transmission.transmission_id:
            session.transmissions[transmission.transmission_id] = transmission
        session.active_drivers.add(transmission.driver_code)
        if transmission.lap_number is not None:
            session.current_lap = max(session.current_lap, transmission.lap_number)
        session.session_key = transmission.session_key


async def _build_system_status(app: FastAPI) -> WebSocketEvent:
    """
    Build a SYSTEM_STATUS WebSocket event from current application state.

    Args:
        app: FastAPI application instance.

    Returns:
        WebSocketEvent with session status payload.
    """
    session: SessionState = app.state.session
    decoder: RadioInterceptDecoder = app.state.decoder
    engine: RehearsalEngine | None = app.state.rehearsal_engine
    agent: RadioInterceptAgent = app.state.agent
    budget_snap = await agent.budget_guard.snapshot(session.session_key)
    payload: dict[str, Any] = {
        "mode": session.mode,
        "session_key": session.session_key,
        "circuit": session.circuit,
        "transmission_count": len(session.transmissions),
        "active_drivers": sorted(session.active_drivers),
        "current_lap": session.current_lap,
        "collection_size": decoder._vector_store.collection_size(),
        "llm_budget": agent.budget_guard.to_public_dict(budget_snap),
    }
    if engine is not None:
        payload["rehearsal_progress"] = engine.get_progress()
    return WebSocketEvent(
        event_type=StreamEventType.SYSTEM_STATUS,
        payload=payload,
        session_key=session.session_key,
        emitted_at=datetime.now(tz=UTC),
    )
