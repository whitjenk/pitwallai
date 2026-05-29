"""UNSUBSCRIBE command."""

from __future__ import annotations

from whatsapp.subscribe_flow import handle_unsubscribe


async def handle_unsubscribe_command(phone_number: str, race_key: str) -> str:
    _ = race_key
    return await handle_unsubscribe(phone_number)
