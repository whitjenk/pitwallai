"""SUBSCRIBE command."""

from __future__ import annotations

from whatsapp.subscribe_flow import handle_subscribe


async def handle_subscribe_command(phone_number: str, race_key: str) -> str:
    _ = race_key
    messages = await handle_subscribe(phone_number)
    return "\n\n".join(messages)
