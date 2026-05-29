"""OpenF1 outage vs quiet-race recap framing."""

from __future__ import annotations

from intelligence.called_recap import (
    CalledRaceRecap,
    render_called_recap_whatsapp,
)
from intelligence.called_recap_page import render_called_recap_share_html


def test_outage_recap_not_quiet_verdict() -> None:
    recap = CalledRaceRecap(
        race_key="2026_monaco",
        race_label="Monaco GP",
        moments=(),
        share_token="t",
        data_unavailable=True,
    )
    msg = render_called_recap_whatsapp(recap, share_url=None)
    assert "live data unavailable" in msg.lower()
    assert "zero strategic moments" not in msg


def test_outage_share_page() -> None:
    recap = CalledRaceRecap(
        race_key="2026_monaco",
        race_label="Monaco GP",
        moments=(),
        share_token="t",
        data_unavailable=True,
    )
    html = render_called_recap_share_html(recap)
    assert "OpenF1 was unreachable" in html
    assert "quiet-race verdict" in html


def test_openf1_health_unavailable_after_threshold() -> None:
    from openf1.health import openf1_health, record_openf1_failure, reset_openf1_health

    reset_openf1_health()
    for _ in range(3):
        record_openf1_failure(RuntimeError("503"))
    assert openf1_health().is_unavailable
