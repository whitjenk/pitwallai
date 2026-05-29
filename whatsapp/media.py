"""Meta WhatsApp media download helper (for inbound images).

Two-step protocol:
  1. GET /{media_id} → JSON with a short-lived signed `url`
  2. GET that url with the same Bearer token → image bytes
"""

from __future__ import annotations

import httpx
from loguru import logger

from whatsapp.settings import get_whatsapp_settings

_GRAPH_API_VERSION = "v18.0"
_MAX_BYTES = 8 * 1024 * 1024  # 8 MiB — well above a typical phone screenshot


async def download_media(media_id: str) -> tuple[bytes, str]:
    """Fetch an inbound image's bytes and mime type by media_id.

    Returns (bytes, mime_type). Raises httpx.HTTPError on failure.
    """
    settings = get_whatsapp_settings()
    token = settings.whatsapp_token.strip()
    if not token:
        raise RuntimeError("WHATSAPP_TOKEN unset — cannot download media")

    headers = {"Authorization": f"Bearer {token}"}
    meta_url = f"https://graph.facebook.com/{_GRAPH_API_VERSION}/{media_id}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        meta = await client.get(meta_url, headers=headers)
        meta.raise_for_status()
        payload = meta.json()
        download_url = payload.get("url")
        mime_type = str(payload.get("mime_type", "image/jpeg"))
        if not download_url:
            raise RuntimeError(f"Meta media metadata missing url: {payload}")

        # Stream so we can cap bytes
        async with client.stream("GET", download_url, headers=headers) as resp:
            resp.raise_for_status()
            buf = bytearray()
            async for chunk in resp.aiter_bytes():
                buf.extend(chunk)
                if len(buf) > _MAX_BYTES:
                    logger.warning("Inbound media exceeded {} bytes; truncating", _MAX_BYTES)
                    break
            return bytes(buf), mime_type
