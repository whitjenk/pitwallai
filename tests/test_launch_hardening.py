"""Launch-hardening guards: fantasy-lock timing, WhatsApp 24h window,
receipts-only mode, and price-catalog freshness."""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest

from scheduler.calendar import get_race_weekend


# ---- Fantasy lock timing ----------------------------------------------------

def test_monaco_lock_is_at_qualifying_not_before_race() -> None:
    monaco = get_race_weekend("2026_monaco")
    assert monaco is not None
    # F1 Fantasy locks at the start of qualifying (Saturday), not before the race.
    assert monaco.fantasy_lock_utc == monaco.qualifying_utc
    # Saturday lock, not Sunday: well before the race.
    assert monaco.fantasy_lock_utc < monaco.race_utc - timedelta(hours=12)


# ---- WhatsApp 24h window ----------------------------------------------------

def _resp(code: int) -> httpx.Response:
    return httpx.Response(
        400,
        json={"error": {"code": code, "message": "x"}},
        request=httpx.Request("POST", "https://graph.facebook.com/x/messages"),
    )


def test_meta_error_code_parses_window_code() -> None:
    from whatsapp.sender import _meta_error_code

    exc = httpx.HTTPStatusError("400", request=_resp(131047).request, response=_resp(131047))
    assert _meta_error_code(exc) == 131047


@pytest.mark.asyncio
async def test_send_message_raises_window_error_outside_24h(monkeypatch) -> None:
    from whatsapp import sender

    class _FakeSettings:
        whatsapp_phone_number_id = "123"
        whatsapp_token = "tok"

        def whatsapp_configured(self) -> bool:
            return True

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return _resp(131047)

    monkeypatch.setattr(sender, "get_whatsapp_settings", lambda: _FakeSettings())
    monkeypatch.setattr(sender.httpx, "AsyncClient", lambda *a, **k: _FakeClient())

    with pytest.raises(sender.WhatsAppWindowError):
        await sender.send_message("+15551234567", "hi")


# ---- Receipts-only mode -----------------------------------------------------

def test_picks_broadcast_enabled_default_on() -> None:
    from pitwallai.feature_flags import picks_broadcast_enabled

    assert picks_broadcast_enabled() is True


@pytest.mark.asyncio
async def test_quali_broadcast_skipped_in_receipts_only(monkeypatch) -> None:
    monkeypatch.setenv("PITWALL_PICKS_BROADCAST_ENABLED", "0")
    from scheduler import jobs

    def _boom():
        raise AssertionError("strategist must not run in receipts-only mode")

    monkeypatch.setattr(jobs, "_strategist", _boom)
    # Should early-return without touching the strategist or cache health.
    await jobs.job_quali_broadcast("2026_monaco")


# ---- OpenF1 404-as-empty ----------------------------------------------------

@pytest.mark.asyncio
async def test_openf1_404_treated_as_empty(monkeypatch) -> None:
    """OpenF1 returns 404 for an empty result set — must degrade to [], so
    find_session_key returns None instead of raising (which would crash the
    race monitor)."""
    from openf1 import cache, client as of1

    async def _miss(_key):
        return None

    monkeypatch.setattr(cache, "cache_get", _miss)

    class _Resp:
        status_code = 404

        def raise_for_status(self):  # pragma: no cover - must not be called
            raise AssertionError("404 should be handled before raise_for_status")

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return _Resp()

    monkeypatch.setattr(of1.httpx, "AsyncClient", lambda *a, **k: _FakeClient())

    c = of1.OpenF1Client()
    sk = await c.find_session_key(year=2026, circuit_short_name="Monaco", session_name="Race")
    assert sk is None


# ---- Price freshness --------------------------------------------------------

def test_catalog_age_days_flags_stale_january_prices() -> None:
    from fantasy.price_catalog import catalog_age_days, load_price_catalog

    load_price_catalog()
    age = catalog_age_days()
    # prices.json ships with updated_at=2026-01-01 — must read as clearly stale.
    assert age is not None
    assert age > 100
