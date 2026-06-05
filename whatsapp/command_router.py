"""
Inbound WhatsApp command router.

Parses raw message text → dispatches to handler → returns reply string.
Never raises. Always returns a string the caller can send back.
"""

from __future__ import annotations

from loguru import logger

from whatsapp.commands import registry
from whatsapp.commands._utils import is_known_driver_code
from whatsapp.sender import mask_phone

COMMAND_MAP = {
    "team": "team",
    "picks": "picks",
    "help": "help",
    "streak": "streak",
    "history": "history",
    "subscribe": "subscribe",
    "unsubscribe": "unsubscribe",
}


async def route(raw_text: str, phone_number: str, race_key: str) -> str:
    """
    Parse raw inbound message and dispatch to handler.

    Returns the reply string to send back to the user.
    Never raises — unknown input returns HELP text.
    """
    from whatsapp.intent import resolve_intent

    canonical = resolve_intent(raw_text)
    if canonical is not None:
        raw_text = canonical

    normalized = raw_text.strip().upper()
    token = normalized.split()[0] if normalized else ""

    cmd_key = token.lower()
    if cmd_key in COMMAND_MAP:
        cmd = COMMAND_MAP[cmd_key]
        handler = registry.get(cmd)
        if handler:
            try:
                return await handler(phone_number=phone_number, race_key=race_key)
            except Exception as exc:
                logger.error(
                    "command_handler_error cmd={} phone={} error={}",
                    cmd,
                    mask_phone(phone_number),
                    exc,
                )
                return _error_reply()

    if 2 <= len(token) <= 4 and token.isalpha() and is_known_driver_code(token):
        from whatsapp.commands.driver import handle_driver

        try:
            return await handle_driver(
                driver_code=token,
                phone_number=phone_number,
                race_key=race_key,
            )
        except Exception as exc:
            logger.error(
                "driver_command_error code={} phone={} error={}",
                token,
                mask_phone(phone_number),
                exc,
            )
            return _error_reply()

    from whatsapp.commands.help import handle_help

    return await handle_help(phone_number=phone_number, race_key=race_key)


def _error_reply() -> str:
    return (
        "Something went wrong on our end. Try again in a moment.\n\n"
        "Reply *HELP* for available commands."
    )
