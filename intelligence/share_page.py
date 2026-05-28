"""Accessible HTML share pages (brand-aligned, color-blind friendly)."""

from __future__ import annotations

from html import escape

from intelligence.recap_metrics import TrendKind
from intelligence.season_recap import SeasonRecap, SessionSnapshot

# PitWallAI design tokens — teal vs amber (not red/green) for deuteranopia safety.
_SHARE_PAGE_CSS = """
:root {
  --pw-bg: #070b16;
  --pw-surface-start: #101a33;
  --pw-surface-end: #0a1021;
  --pw-text: #f5f8ff;
  --pw-muted: #a9b6d3;
  --pw-stroke: rgba(158, 193, 255, 0.22);
  --pw-accent: #5ea1ff;
  --pw-trend-up: #5ae0c8;
  --pw-trend-up-bg: rgba(90, 224, 200, 0.14);
  --pw-trend-down: #ffb020;
  --pw-trend-down-bg: rgba(255, 176, 32, 0.14);
  --pw-trend-flat: #c5d0ea;
  --pw-trend-flat-bg: rgba(197, 208, 234, 0.12);
}
* { box-sizing: border-box; }
body {
  font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: var(--pw-bg);
  color: var(--pw-text);
  margin: 0;
}
.wrap { max-width: 720px; margin: 40px auto; padding: 0 16px; }
.card {
  background: linear-gradient(155deg, var(--pw-surface-start) 0%, var(--pw-surface-end) 100%);
  border: 1px solid var(--pw-stroke);
  border-radius: 20px;
  padding: 28px;
  box-shadow: 0 24px 60px rgba(0,0,0,0.45), inset 0 1px 0 rgba(255,255,255,0.08);
}
.eyebrow {
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--pw-muted);
}
h1 { margin: 8px 0 20px; font-size: 32px; font-weight: 700; line-height: 1.1; }
.hero {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 12px 16px;
  margin-bottom: 20px;
}
.hero-value { font-size: 52px; font-weight: 700; line-height: 1; }
.hero-label { font-size: 14px; color: var(--pw-muted); max-width: 220px; }
.line { margin: 10px 0; font-size: 16px; line-height: 1.45; }
.session-panel {
  margin: 18px 0;
  padding: 14px 16px;
  border-radius: 12px;
  border: 1px solid var(--pw-stroke);
  background: rgba(15, 23, 42, 0.55);
}
.session-title { font-size: 13px; font-weight: 600; color: var(--pw-muted); margin-bottom: 8px; }
.session-row { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; font-size: 15px; }
.trend-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 600;
  border: 1px solid transparent;
}
.trend-pill[data-trend="up"] {
  color: var(--pw-trend-up);
  background: var(--pw-trend-up-bg);
  border-color: rgba(90, 224, 200, 0.35);
}
.trend-pill[data-trend="down"] {
  color: var(--pw-trend-down);
  background: var(--pw-trend-down-bg);
  border-color: rgba(255, 176, 32, 0.35);
}
.trend-pill[data-trend="flat"] {
  color: var(--pw-trend-flat);
  background: var(--pw-trend-flat-bg);
  border-color: rgba(197, 208, 234, 0.28);
}
.cta { margin-top: 20px; font-size: 14px; color: var(--pw-accent); }
"""


def _trend_pill_html(
    trend: TrendKind,
    delta_pp: int | None,
    *,
    prefix: str = "",
    label: str | None = None,
    aria_label: str | None = None,
) -> str:
    """
    Accessible trend badge: icon + words + color (never color-only).

    Up = teal, Down = amber, Flat = neutral (color-blind safe pair).
    """
    if trend == "none":
        return ""
    if trend == "up":
        icon = "↑"
        default_label = f"Improved {delta_pp} pts"
        default_aria = f"{prefix}Improved {delta_pp} percentage points versus previous race"
    elif trend == "down":
        icon = "↓"
        default_label = f"Declined {abs(delta_pp or 0)} pts"
        default_aria = f"{prefix}Declined {abs(delta_pp or 0)} percentage points versus previous race"
    else:
        icon = "→"
        default_label = "Steady vs last race"
        default_aria = f"{prefix}Steady versus previous race"
    label = label or default_label
    aria = aria_label or default_aria
    return (
        f'<span class="trend-pill" data-trend="{trend}" '
        f'role="status" aria-label="{escape(aria)}">'
        f'<span aria-hidden="true">{icon}</span> {escape(label)}</span>'
    )


def render_season_share_html(
    recap: SeasonRecap,
    *,
    session: SessionSnapshot | None,
    page_title: str,
    meta_description: str,
) -> str:
    """Render full season recap share page HTML."""
    vs_community = int(round(recap.personalized_accuracy_pct - recap.community_accuracy_pct))
    if vs_community > 0:
        community_pill = _trend_pill_html(
            "up",
            vs_community,
            label=f"+{vs_community} vs community",
            aria_label=f"Ahead of community baseline by {vs_community} percentage points",
        )
    elif vs_community < 0:
        community_pill = _trend_pill_html(
            "down",
            abs(vs_community),
            label=f"{vs_community} vs community",
            aria_label=f"Behind community baseline by {abs(vs_community)} percentage points",
        )
    else:
        community_pill = _trend_pill_html(
            "flat",
            0,
            label="Matched community",
            aria_label="Matched community baseline accuracy",
        )

    session_block = ""
    if session is not None:
        sign = "+" if session.avg_points_delta >= 0 else ""
        mom_pill = _trend_pill_html(session.momentum_trend, session.momentum_delta_pp)
        session_block = f"""
      <div class="session-panel">
        <div class="session-title">Latest race session · {escape(session.circuit_label)}</div>
        <div class="session-row">
          <span><strong>{session.hit_pct:.0f}%</strong> hit</span>
          <span aria-hidden="true">·</span>
          <span><strong>{sign}{session.avg_points_delta:.1f}</strong> avg pts</span>
          {mom_pill}
        </div>
      </div>"""

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(page_title)}</title>
  <meta name="description" content="{escape(meta_description)}" />
  <link rel="canonical" href="{escape(recap.share_url)}" />
  <meta property="og:type" content="website" />
  <meta property="og:site_name" content="PitWallAI" />
  <meta property="og:title" content="{escape(page_title)}" />
  <meta property="og:description" content="{escape(meta_description)}" />
  <meta property="og:url" content="{escape(recap.share_url)}" />
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="{escape(page_title)}" />
  <meta name="twitter:description" content="{escape(meta_description)}" />
  <style>{_SHARE_PAGE_CSS}</style>
</head>
<body>
  <main class="wrap">
    <section class="card" aria-labelledby="recap-title">
      <div class="eyebrow">PitWallAI · Season Recap {recap.season}</div>
      <h1 id="recap-title">🏁 Season complete</h1>
      <div class="hero">
        <div>
          <div class="hero-value">{recap.personalized_accuracy_pct:.0f}%</div>
          <div class="hero-label">Your personalized picks accuracy</div>
        </div>
        {community_pill}
      </div>
      <div class="line"><strong>Community baseline:</strong> {recap.community_accuracy_pct:.0f}%</div>
      {session_block}
      <div class="line"><strong>Best call:</strong> {escape(recap.best_call)}</div>
      <div class="line"><strong>Worst call:</strong> {escape(recap.worst_call)}</div>
      <div class="line"><strong>Biggest signal:</strong> {escape(recap.biggest_signal)}</div>
      <div class="cta">Share this card with your league · {escape(recap.share_url)}</div>
    </section>
  </main>
</body>
</html>"""
