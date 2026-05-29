"""Inbound WhatsApp media validation."""

from __future__ import annotations

import pytest

from whatsapp.media import (
    InvalidMediaError,
    MediaTooLargeError,
    _host_allowed,
    _sniff_mime,
)


def test_host_allowlist_rejects_unknown():
    assert not _host_allowed("https://evil.example.com/secret.jpg")
    assert _host_allowed("https://lookaside.fbsbx.com/whatsapp_media/abc")
    assert _host_allowed("https://graph.facebook.com/v18.0/123")


def test_sniff_jpeg_png_webp():
    assert _sniff_mime(b"\xff\xd8\xff\x00") == "image/jpeg"
    assert _sniff_mime(b"\x89PNG\r\n\x1a\n" + b"x" * 4) == "image/png"
    assert _sniff_mime(b"RIFF" + b"x" * 4 + b"WEBP") == "image/webp"
    assert _sniff_mime(b"not an image") is None


@pytest.mark.asyncio
async def test_download_rejects_oversize(monkeypatch):
    from whatsapp import media as media_mod

    class FakeResp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "url": "https://lookaside.fbsbx.com/x",
                "mime_type": "image/jpeg",
            }

    class FakeStream:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            return None

        def raise_for_status(self) -> None:
            return None

        async def aiter_bytes(self):
            yield b"\xff\xd8\xff" + (b"x" * (media_mod._MAX_BYTES + 1))

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            return None

        async def get(self, url, headers=None):
            return FakeResp()

        def stream(self, method, url, headers=None):
            return FakeStream()

    monkeypatch.setattr(
        media_mod,
        "get_whatsapp_settings",
        lambda: type("S", (), {"whatsapp_token": "tok"})(),
    )
    monkeypatch.setattr(media_mod.httpx, "AsyncClient", FakeClient)

    with pytest.raises(MediaTooLargeError):
        await media_mod.download_media("media123")


@pytest.mark.asyncio
async def test_download_rejects_bad_magic(monkeypatch):
    from whatsapp import media as media_mod

    class FakeResp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "url": "https://lookaside.fbsbx.com/x",
                "mime_type": "image/jpeg",
            }

    class FakeStream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            return None

        def raise_for_status(self) -> None:
            return None

        async def aiter_bytes(self):
            yield b"not-a-real-image"

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            return None

        async def get(self, url, headers=None):
            return FakeResp()

        def stream(self, method, url, headers=None):
            return FakeStream()

    monkeypatch.setattr(
        media_mod,
        "get_whatsapp_settings",
        lambda: type("S", (), {"whatsapp_token": "tok"})(),
    )
    monkeypatch.setattr(media_mod.httpx, "AsyncClient", FakeClient)

    with pytest.raises(InvalidMediaError):
        await media_mod.download_media("media123")
