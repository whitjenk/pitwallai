#!/usr/bin/env python3
"""PitWallAI CLI entry point."""

from __future__ import annotations

import argparse
import os
from dataclasses import replace

import uvicorn
from loguru import logger

from api.server import create_app
from db.session import init_db
from intelligence.context import init_orchestrator_context
from pitwallai.agents.radio_intercept.config import DecodeBackend, PitWallSettings
from whatsapp.webhook import router as whatsapp_router

# ASGI entry for Railway / `uvicorn main:app` (see railway.toml)
app = create_app(
    mode=os.environ.get("PITWALL_MODE", "rehearsal"),
    rehearsal_speed=float(os.environ.get("PITWALL_REHEARSAL_SPEED", "3.0")),
)
app.include_router(whatsapp_router)


@app.on_event("startup")
async def _whatsapp_startup() -> None:
    """Ensure DB tables exist and load circuit profiles into orchestrator context."""
    import asyncio

    mode = os.environ.get("PITWALL_MODE", "rehearsal")
    from pitwallai.launch_validate import assert_live_ready

    assert_live_ready(mode=mode)
    init_orchestrator_context()
    await init_db()
    from pitwallai.feature_flags import constructor_strategy_enabled

    if constructor_strategy_enabled():
        from intelligence.constructor_strategy import seed_constructor_profiles

        asyncio.create_task(seed_constructor_profiles())


def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments for PitWallAI.

    Returns:
        Parsed argparse namespace.
    """
    parser = argparse.ArgumentParser(description="PitWallAI Radio Intercept Decoder")
    parser.add_argument(
        "--mode",
        choices=["live", "rehearsal"],
        default="rehearsal",
        help="Operating mode: live OpenF1 ingest or scripted rehearsal",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="HTTP port for FastAPI and dashboard",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=3.0,
        help="Rehearsal playback speed multiplier",
    )
    parser.add_argument(
        "--decode-backend",
        choices=[b.value for b in DecodeBackend],
        default=None,
        help="Decode strategy: rules (default, no LLM), hybrid, or llm",
    )
    parser.add_argument(
        "--llm-model",
        default=None,
        help="Pydantic AI model id when using llm/hybrid (e.g. openai:gpt-4o-mini)",
    )
    parser.add_argument(
        "--bind-host",
        default=None,
        help="Bind address (default: PITWALL_BIND_HOST or 127.0.0.1)",
    )
    return parser.parse_args()


def build_settings(args: argparse.Namespace) -> PitWallSettings:
    """
    Merge CLI flags into PitWallSettings.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Resolved settings.
    """
    settings = PitWallSettings.from_env()
    if args.decode_backend is not None:
        settings = replace(
            settings,
            decode_backend=DecodeBackend(args.decode_backend),
            llm_model=args.llm_model or settings.llm_model,
        )
    elif args.llm_model is not None:
        settings = replace(settings, llm_model=args.llm_model)
    if args.bind_host is not None:
        settings = replace(settings, bind_host=args.bind_host)
    return settings


def main() -> None:
    """Start PitWallAI with FastAPI, dashboard, and optional rehearsal playback."""
    args = parse_args()
    settings = build_settings(args)
    mode_label = args.mode.upper()
    print(f"PitWallAI v1.0 — RADIO INTERCEPT DECODER — {mode_label}")
    print(f"Decode backend: {settings.decode_backend.value} (LLM: {settings.llm_model or 'disabled'})")

    if settings.decode_backend != DecodeBackend.RULES and not settings.llm_enabled:
        logger.warning(
            "LLM backend requested but PITWALL_LLM_MODEL is unset — "
            "set e.g. PITWALL_LLM_MODEL=openai:gpt-4o-mini or use --decode-backend rules"
        )
    if settings.decode_backend != DecodeBackend.RULES:
        if not settings.llm_budget_acknowledged:
            print(
                "WARNING: LLM/hybrid requires PITWALL_LLM_BUDGET_ACK=1 — "
                "running rules-only until acknowledged (.env.example)"
            )
        else:
            print(
                f"LLM budget caps: {settings.llm_max_calls_per_session} calls/session, "
                f"${settings.llm_max_estimated_usd_per_session:.2f}/session, "
                f"${settings.llm_max_estimated_usd_per_day:.2f}/day"
            )

    app = create_app(mode=args.mode, rehearsal_speed=args.speed, settings=settings)

    if args.mode == "rehearsal":
        logger.bind(speed=args.speed).info(
            "Rehearsal mode — Monaco scenario scheduled on API startup"
        )

    host = settings.bind_host
    logger.info("Dashboard → http://localhost:{}/dashboard", args.port)
    logger.info("Stream  → ws://localhost:{}/ws/stream", args.port)

    uvicorn.run(app, host=host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
