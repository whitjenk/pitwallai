"""Bolt wiring — a thin Socket Mode layer over the plain handlers.

No F1 logic: this module only turns a Slack slash command into a call to
:func:`slack_app.handlers.handle` and turns the returned :class:`Reply` back
into a Slack response. Socket Mode means one long-running process and no public
URL (see ``docs/slack_setup.md``).
"""

from __future__ import annotations

import asyncio
import os

from loguru import logger

import store
from core.price_catalog import load_price_catalog
from feeds.fantasy_prices import load_prices_from_store, refresh_prices
from slack_app.handlers import handle

# How often the background task re-fetches F1 Fantasy prices.
PRICE_REFRESH_INTERVAL_SECONDS = 12 * 3600

# Env vars the Socket Mode app needs. SLACK_BOT_TOKEN authorises chat:write;
# SLACK_APP_TOKEN (an app-level token with connections:write) opens the socket.
BOT_TOKEN_ENV = "SLACK_BOT_TOKEN"
APP_TOKEN_ENV = "SLACK_APP_TOKEN"
REQUIRED_TOKENS = (BOT_TOKEN_ENV, APP_TOKEN_ENV)


def missing_tokens() -> list[str]:
    """Names of the required token env vars that are unset or blank."""
    return [name for name in REQUIRED_TOKENS if not os.environ.get(name, "").strip()]


def build_app():
    """Build the Bolt ``AsyncApp`` with the ``/pitwall`` command registered."""
    from slack_bolt.async_app import AsyncApp

    app = AsyncApp(token=os.environ[BOT_TOKEN_ENV])

    @app.command("/pitwall")
    async def pitwall_command(ack, command, respond):  # type: ignore[no-untyped-def]
        await ack()
        result = await handle(
            text=command.get("text", ""),
            user_id=command["user_id"],
            team_id=command.get("team_id", ""),
            display_name=command.get("user_name"),
        )
        # A handler returns one Reply, or several (e.g. `lock`: a private
        # confirmation plus a public one-liner). Post each in order.
        replies = result if isinstance(result, list) else [result]
        for reply in replies:
            await respond(text=reply.text, response_type=reply.visibility)

    return app


async def _price_refresh_loop(
    *, interval_seconds: int = PRICE_REFRESH_INTERVAL_SECONDS
) -> None:
    """Refresh F1 Fantasy prices now, then every ``interval_seconds`` forever.

    Runs inside the Bolt process (no APScheduler). Each refresh is best-effort:
    on failure it keeps the last good prices and tries again next cycle.
    """
    while True:
        await refresh_prices()
        await asyncio.sleep(interval_seconds)


async def run() -> None:
    """Create the DB if needed and serve the app over Socket Mode forever."""
    from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

    await store.init_db()
    # Load the committed baseline, then overlay the last cached refresh so
    # prices are current before the first live fetch completes and survive a
    # redeploy (Railway wipes the filesystem; the store is on a volume).
    load_price_catalog()
    await load_prices_from_store()
    app = build_app()
    refresh_task = asyncio.create_task(_price_refresh_loop())
    handler = AsyncSocketModeHandler(app, os.environ[APP_TOKEN_ENV])
    logger.info("PitWallAI Slack app starting (Socket Mode)…")
    try:
        await handler.start_async()
    finally:
        refresh_task.cancel()
