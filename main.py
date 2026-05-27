#!/usr/bin/env python3
"""PitWallAI CLI entry point."""

from __future__ import annotations

import argparse

import uvicorn
from loguru import logger

from api.server import create_app


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
    return parser.parse_args()


def main() -> None:
    """Start PitWallAI with FastAPI, dashboard, and optional rehearsal playback."""
    args = parse_args()
    mode_label = args.mode.upper()
    print(f"PitWallAI v1.0 — RADIO INTERCEPT DECODER — {mode_label}")

    app = create_app(mode=args.mode, rehearsal_speed=args.speed)

    if args.mode == "rehearsal":
        logger.bind(speed=args.speed).info(
            "Rehearsal mode — Monaco scenario scheduled on API startup"
        )

    host = "0.0.0.0"
    logger.info("Dashboard → http://localhost:{}/dashboard", args.port)
    logger.info("Stream  → ws://localhost:{}/ws/stream", args.port)

    uvicorn.run(app, host=host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
