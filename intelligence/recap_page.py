"""Screenshot-friendly public race recap page."""

from __future__ import annotations

from html import escape

from db.models import ShareCard
from intelligence.repository import get_share_card_by_token


_RECAP_CSS = """
:root {
  --pw-bg: #0b0f14;
  --pw-card: #141a22;
  --pw-text: #e8edf4;
  --pw-muted: #8b949e;
  --pw-accent: #ff6b00;
  --pw-ok: #3fb950;
  --pw-miss: #d29922;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: system-ui, -apple-system, sans-serif;
  background: var(--pw-bg);
  color: var(--pw-text);
}
.wrap {
  max-width: 390px;
  margin: 0 auto;
  padding: 20px 16px 32px;
}
.card {
  background: var(--pw-card);
  border-radius: 16px;
  padding: 20px;
  border: 1px solid #2a3441;
}
.eyebrow {
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--pw-muted);
}
h1 { font-size: 22px; margin: 8px 0 4px; }
.badge {
  display: inline-block;
  background: #1c2a3a;
  border-radius: 999px;
  padding: 6px 12px;
  font-size: 14px;
  margin: 8px 0 16px;
}
.pick {
  border-top: 1px solid #2a3441;
  padding: 12px 0;
  font-size: 14px;
}
.pick strong { color: var(--pw-accent); }
.ok { color: var(--pw-ok); }
.miss { color: var(--pw-miss); }
.stat { font-size: 13px; color: var(--pw-muted); margin-top: 4px; }
.cta {
  margin-top: 20px;
  text-align: center;
  font-size: 13px;
  color: var(--pw-muted);
}
.cta a { color: var(--pw-accent); }
"""


def render_recap_share_html(card: ShareCard) -> str:
    """Mobile-width recap page — no phone or league PII."""
    picks_html = ""
    for detail in card.pick_details or []:
        ok = detail.get("was_correct")
        mark = "✅" if ok else "❌" if ok is False else "·"
        cls = "ok" if ok else "miss" if ok is False else ""
        driver = detail.get("transfer_in") or detail.get("driver_code") or "?"
        out = detail.get("transfer_out")
        label = f"{out} → {driver}" if out else str(driver)
        delta = detail.get("actual_points_delta")
        delta_txt = f" ({delta:+.0f} pts)" if delta is not None else ""
        picks_html += (
            f'<div class="pick"><span class="{cls}">{mark}</span> '
            f"<strong>{escape(label)}</strong>{escape(delta_txt)}"
            f'<div class="stat">{escape((detail.get("reasoning") or "")[:120])}</div></div>'
        )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>PitWallAI · {escape(card.race_name)} recap</title>
  <meta name="description" content="PitWallAI race recap — {card.picks_correct}/{card.picks_total} picks" />
  <style>{_RECAP_CSS}</style>
</head>
<body>
  <main class="wrap">
    <article class="card">
      <div class="eyebrow">PitWallAI · Race recap</div>
      <h1>{escape(card.race_name)}</h1>
      <div class="badge">{card.picks_correct}/{card.picks_total} picks · {card.accuracy_pct:.0f}%</div>
      <div class="stat">Season GP hit rate: {card.season_accuracy_pct:.0f}%</div>
      {picks_html}
      <div class="cta">Subscribe at <a href="https://pitwallai.app">pitwallai.app</a></div>
    </article>
  </main>
</body>
</html>"""


async def render_recap_page_for_token(share_token: str) -> str | None:
    card = await get_share_card_by_token(share_token)
    if card is None or not card.is_public:
        return None
    return render_recap_share_html(card)
