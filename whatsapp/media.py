"""Meta WhatsApp media download helper (for inbound images).

Two-step protocol:
  1. GET /{media_id} → JSON with a short-lived signed `url`
  2. GET that url with the same Bearer token → image bytes
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx
from loguru import logger

from whatsapp.settings import get_whatsapp_settings

_GRAPH_API_VERSION = "v18.0"
_MAX_BYTES = 8 * 1024 * 1024  # 8 MiB — well above a typical phone screenshot

# Meta CDN hosts returned by the media metadata `url` field.
_ALLOWED_DOWNLOAD_HOST_SUFFIXES = (
    ".facebook.com",
    ".fbcdn.net",
    ".fbsbx.com",
)


class MediaDownloadError(Exception):
    """Base class for inbound media validation failures."""


class MediaTooLargeError(MediaDownloadError):
    """Download exceeded the size cap."""


class InvalidMediaError(MediaDownloadError):
    """URL, MIME, or content failed validation."""


def _host_allowed(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    if host == "graph.facebook.com":
        return True
    return any(host.endswith(suffix) for suffix in _ALLOWED_DOWNLOAD_HOST_SUFFIXES)


def _sniff_mime(data: bytes) -> str | None:
    if len(data) >= 3 and data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


async def download_media(media_id: str) -> tuple[bytes, str]:
    """Fetch an inbound image's bytes and mime type by media_id.

    Returns (bytes, mime_type). Raises MediaDownloadError on validation failure.
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
        reported_mime = str(payload.get("mime_type", "image/jpeg"))
        if not download_url:
            raise RuntimeError(f"Meta media metadata missing url: {payload}")
        if not _host_allowed(str(download_url)):
            raise InvalidMediaError(f"download URL host not allowlisted: {download_url!r}")

        buf = bytearray()
        async with client.stream("GET", download_url, headers=headers) as resp:
            resp.raise_for_status()
            async for chunk in resp.aiter_bytes():
                buf.extend(chunk)
                if len(buf) > _MAX_BYTES:
                    raise MediaTooLargeError(
                        f"inbound media exceeded {_MAX_BYTES} bytes"
                    )

        data = bytes(buf)
        sniffed = _sniff_mime(data)
        if sniffed is None:
            raise InvalidMediaError("content is not a supported JPEG/PNG/WebP image")
        if reported_mime.startswith("image/") and sniffed != reported_mime:
            logger.warning(
                "Meta mime_type={} disagrees with sniffed {}; using sniffed",
                reported_mime,
                sniffed,
            )
        return data, sniffed
