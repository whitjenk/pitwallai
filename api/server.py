"""FastAPI web surface: picks API, public share pages, and OG cards."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from loguru import logger

from api.picks import router as picks_router
from api.picks_auth import require_picks_api_key
from intelligence.season_recap import (
    build_latest_session_snapshot,
    build_season_recap,
    parse_share_token,
)
from intelligence.share_page import render_season_share_html
from openf1.client import OpenF1Client
from pitwallai.llm.settings import PitWallSettings

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_ROOT / "api" / "static"


def create_app(
    mode: str = "rehearsal",
    settings: PitWallSettings | None = None,
) -> FastAPI:
    """
    Create and configure the PitWallAI FastAPI application.

    Args:
        mode: Operating mode ('live' enforces full WhatsApp config; anything
            else runs in local/non-live mode).
        settings: Optional pre-built settings; loaded from env when omitted.

    Returns:
        Configured FastAPI instance.
    """
    pitwall_settings = settings or PitWallSettings.from_env()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Initialize app components on startup, tear them down on shutdown."""
        # ----- startup -----
        log = logger.bind(mode=mode)
        log.info("Initializing PitWallAI components")

        from pitwallai.launch_validate import assert_live_ready

        assert_live_ready(mode=mode)

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
        from whatsapp.app_runtime import register_fastapi_app

        register_fastapi_app(app)
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

        log.bind(
            decode_backend=pitwall_settings.decode_backend.value,
            llm_enabled=pitwall_settings.llm_enabled,
        ).info("Pick pipeline configured")

        from agents.race_monitor import resume_monitors_on_startup
        from agents.base import AgentRunDependencies

        monitor_deps = AgentRunDependencies(
            openf1_client=OpenF1Client(),
            settings=pitwall_settings,
        )
        await resume_monitors_on_startup(monitor_deps)

        from pitwallai.feature_flags import constructor_strategy_enabled

        if constructor_strategy_enabled():
            from intelligence.constructor_strategy import seed_constructor_profiles

            asyncio.create_task(seed_constructor_profiles())
            log.info("Constructor strategy profile seeder scheduled (background)")
        else:
            log.info("Constructor strategy seeder skipped (flag off)")

        if (
            not get_whatsapp_settings().database_url.strip()
            and pitwall_settings.explanation_cards_enabled
        ):
            from intelligence.demo_picks import build_demo_picks_result

            app.state.last_picks_result = build_demo_picks_result()
            log.info("Loaded demo picks with explanation cards (no DATABASE_URL)")

        log.info("PitWallAI startup complete")

        yield

        # ----- shutdown -----
        await stop_race_scheduler()
        picks_sched = getattr(app.state, "picks_scheduler", None)
        if picks_sched is not None:
            await picks_sched.stop()

    app = FastAPI(
        title="PitWallAI",
        version="1.0",
        lifespan=lifespan,
    )
    app.include_router(picks_router)
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.state.mode = mode
    app.state.settings = pitwall_settings

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

    @app.get("/health")
    async def health() -> dict[str, Any]:
        """Health check endpoint."""
        pitwall_settings: PitWallSettings = app.state.settings
        return {
            "status": "ok",
            "mode": app.state.mode,
            "decode_backend": pitwall_settings.decode_backend.value,
            "llm_configured": pitwall_settings.llm_enabled,
            "llm_model": pitwall_settings.llm_model or None,
            "llm_budget_acknowledged": pitwall_settings.llm_budget_acknowledged,
        }

    @app.get(
        "/api/budget",
        dependencies=[Depends(require_picks_api_key)],
    )
    async def budget_status() -> dict[str, Any]:
        """Return platform LLM spend utilization and caps."""
        from intelligence.spend_guard import get_spend_guard, to_public_dict

        spend = await get_spend_guard()
        return {"platform_spend": to_public_dict(spend)}

    @app.get("/api/season/{token}")
    async def season_recap(token: str) -> dict[str, Any]:
        """Return a public share payload for a season recap token."""
        from pitwallai.feature_flags import season_recap_enabled

        if not season_recap_enabled():
            raise HTTPException(status_code=404, detail="Season recap disabled")
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
        from pitwallai.feature_flags import season_recap_enabled

        if not season_recap_enabled():
            raise HTTPException(status_code=404, detail="Season recap disabled")
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
            og_image_url=f"https://pitwallai.app/og/season/{token}.png",
        )
        return HTMLResponse(content=html)

    @app.get("/recap/{token}", response_class=HTMLResponse)
    async def race_recap_page(token: str) -> HTMLResponse:
        """Public post-race recap share page (token is auth)."""
        from pitwallai.feature_flags import counterfactual_recap_enabled

        if not counterfactual_recap_enabled():
            raise HTTPException(status_code=404, detail="Recap disabled")
        from intelligence.recap_page import render_recap_page_for_token

        html = await render_recap_page_for_token(token)
        if html is None:
            raise HTTPException(status_code=404, detail="Recap not found")
        return HTMLResponse(content=html)

    @app.get("/chips/{token}", response_class=HTMLResponse)
    async def chip_plan_page(token: str) -> HTMLResponse:
        """Public chip plan calendar page."""
        from pitwallai.feature_flags import chips_enabled

        if not chips_enabled():
            raise HTTPException(status_code=404, detail="Chips disabled")
        from intelligence.chips_page import render_chips_page_for_token

        html = await render_chips_page_for_token(token)
        if html is None:
            raise HTTPException(status_code=404, detail="Chip plan not found")
        return HTMLResponse(content=html)

    @app.get("/called/{token}", response_class=HTMLResponse)
    async def called_recap_page(token: str) -> HTMLResponse:
        """Public post-race 'what we called' share page."""
        from intelligence.called_recap_page import render_called_recap_page_for_token

        html = await render_called_recap_page_for_token(token)
        if html is None:
            raise HTTPException(status_code=404, detail="Recap not found")
        return HTMLResponse(content=html)

    _OG_CACHE_HEADERS = {"Cache-Control": "public, max-age=3600"}

    def _png(data: bytes) -> Response:
        return Response(content=data, media_type="image/png", headers=_OG_CACHE_HEADERS)

    @app.get("/og/brand.png", include_in_schema=False)
    async def og_brand() -> Response:
        """Static brand OG card (homepage / sample / results unfurls)."""
        from sharing.og_image import brand_og_png

        return _png(brand_og_png())

    @app.get("/og/called/{token}.png", include_in_schema=False)
    async def og_called(token: str) -> Response:
        """Per-race 'what we called' OG card. Falls back to brand card on error."""
        from intelligence.called_recap import load_called_recap
        from sharing.og_image import brand_og_png, called_recap_og_png

        try:
            recap = await load_called_recap(token)
            if recap is not None:
                return _png(called_recap_og_png(recap))
        except Exception as exc:  # unfurl must still get an image
            logger.warning("og_called render failed token={}: {}", token, exc)
        return _png(brand_og_png())

    @app.get("/og/season/{token}.png", include_in_schema=False)
    async def og_season(token: str) -> Response:
        """Season recap OG card. Falls back to brand card on error."""
        from sharing.og_image import brand_og_png, season_og_png

        try:
            parsed = parse_share_token(token, _season_share_secret())
            if parsed is not None:
                phone, season = parsed
                recap = await build_season_recap(
                    phone=phone,
                    season=season,
                    share_base_url="https://pitwallai.app",
                    share_secret=_season_share_secret(),
                )
                return _png(season_og_png(recap))
        except Exception as exc:  # unfurl must still get an image
            logger.warning("og_season render failed token={}: {}", token, exc)
        return _png(brand_og_png())

    @app.get("/results", include_in_schema=False)
    async def results_page() -> RedirectResponse:
        """Public season hit-rate page (static HTML)."""
        return RedirectResponse(url="/static/results.html", status_code=302)

    @app.get("/sample", include_in_schema=False, response_class=HTMLResponse)
    async def sample_page() -> HTMLResponse:
        """Public preview of a PitWallAI weekend (pick, recap, called card)."""
        from intelligence.sample_page import render_sample_page

        return HTMLResponse(content=render_sample_page())

    @app.get("/", include_in_schema=False, response_class=HTMLResponse)
    async def homepage() -> HTMLResponse:
        """Public marketing homepage with live aggregate stats."""
        from intelligence.homepage import render_homepage_for_request

        html = await render_homepage_for_request()
        return HTMLResponse(content=html)

    @app.get(
        "/api/onboarding/metrics",
        dependencies=[Depends(require_picks_api_key)],
    )
    async def onboarding_metrics_endpoint() -> dict[str, Any]:
        """Operator-only onboarding funnel snapshot + alert state."""
        from dataclasses import asdict
        from intelligence.onboarding_metrics import (
            check_and_alert_onboarding_funnel,
        )

        funnel = await check_and_alert_onboarding_funnel()
        return asdict(funnel)

    return app
