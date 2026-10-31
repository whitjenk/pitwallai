"""Bolt wiring — a thin Socket Mode layer over the plain handlers.

No F1 logic: this module only turns a Slack slash command into a call to
:func:`slack_app.handlers.handle` and turns the returned :class:`Reply` back
into a Slack response. Socket Mode means one long-running process and no public
URL (see ``docs/slack_setup.md``).
"""

from __future__ import annotations

import os

from loguru import logger

import store
from slack_app.handlers import handle

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
        reply = await handle(
            text=command.get("text", ""),
            user_id=command["user_id"],
            team_id=command.get("team_id", ""),
            display_name=command.get("user_name"),
        )
        await respond(text=reply.text, response_type=reply.visibility)

    return app


async def run() -> None:
    """Create the DB if needed and serve the app over Socket Mode forever."""
    from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

    await store.init_db()
    app = build_app()
    handler = AsyncSocketModeHandler(app, os.environ[APP_TOKEN_ENV])
    logger.info("PitWallAI Slack app starting (Socket Mode)…")
    await handler.start_async()
