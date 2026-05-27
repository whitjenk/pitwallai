#!/usr/bin/env python3
"""PitWallAI CLI entry point."""

from __future__ import annotations

import argparse

import uvicorn
from loguru import logger

from api.server import create_app
from pitwallai.agents.radio_intercept.config import DecodeBackend, PitWallSettings


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
        settings = PitWallSettings(
            decode_backend=DecodeBackend(args.decode_backend),
            llm_model=args.llm_model or settings.llm_model,
            llm_escalation_threshold=settings.llm_escalation_threshold,
            llm_max_concurrency=settings.llm_max_concurrency,
            decode_dedup_ttl_seconds=settings.decode_dedup_ttl_seconds,
            embedding_cache_size=settings.embedding_cache_size,
            bind_host=args.bind_host or settings.bind_host,
            cors_origins=settings.cors_origins,
            ws_max_connections=settings.ws_max_connections,
            log_transcripts=settings.log_transcripts,
        )
    elif args.llm_model is not None:
        settings = PitWallSettings(
            decode_backend=settings.decode_backend,
            llm_model=args.llm_model,
            llm_escalation_threshold=settings.llm_escalation_threshold,
            llm_max_concurrency=settings.llm_max_concurrency,
            decode_dedup_ttl_seconds=settings.decode_dedup_ttl_seconds,
            embedding_cache_size=settings.embedding_cache_size,
            bind_host=args.bind_host or settings.bind_host,
            cors_origins=settings.cors_origins,
            ws_max_connections=settings.ws_max_connections,
            log_transcripts=settings.log_transcripts,
        )
    elif args.bind_host is not None:
        settings = PitWallSettings(
            decode_backend=settings.decode_backend,
            llm_model=settings.llm_model,
            llm_escalation_threshold=settings.llm_escalation_threshold,
            llm_max_concurrency=settings.llm_max_concurrency,
            decode_dedup_ttl_seconds=settings.decode_dedup_ttl_seconds,
            embedding_cache_size=settings.embedding_cache_size,
            bind_host=args.bind_host,
            cors_origins=settings.cors_origins,
            ws_max_connections=settings.ws_max_connections,
            log_transcripts=settings.log_transcripts,
        )
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
