"""Command handler registry for the inbound router."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from whatsapp.commands.help import handle_help
from whatsapp.commands.history import handle_history
from whatsapp.commands.picks import handle_picks
from whatsapp.commands.streak import handle_streak
from whatsapp.commands.subscribe import handle_subscribe_command
from whatsapp.commands.team import handle_team
from whatsapp.commands.unsubscribe import handle_unsubscribe_command

CommandHandler = Callable[..., Awaitable[str]]

_registry: dict[str, CommandHandler] = {
    "help": handle_help,
    "streak": handle_streak,
    "team": handle_team,
    "picks": handle_picks,
    "history": handle_history,
    "subscribe": handle_subscribe_command,
    "unsubscribe": handle_unsubscribe_command,
}


def get(command: str) -> CommandHandler | None:
    return _registry.get(command)
