"""Public marketing homepage at `/`.

Three honest live numbers above the fold: active subscribers, season
GP hit rate, races scored. No vs.-the-field comparison until the
methodology is wired (Phase 2). The page is intentionally one-screen,
text-first, and screenshottable — designed for the curious player and
the BD scout, not for the existing subscriber.

Subscriber count is gated behind a reveal threshold (see
`SUBSCRIBER_REVEAL_THRESHOLD`). Showing "23 subscribers" publicly is
worse than not showing the raw number — it anchors the brand to a
volatile early figure and a single unsubscribe events the page. Below
threshold we show a qualitative "early access" badge instead.
"""

from __future__ import annotations

import os
from html import escape


# Default reveal threshold. Override via PITWALL_SUBSCRIBER_REVEAL_THRESHOLD.
# 250 picked as the floor where weekly volatility is dominated by trend
# rather than churn noise.
_DEFAULT_SUBSCRIBER_REVEAL_THRESHOLD = 250


def _subscriber_reveal_threshold() -> int:
    raw = os.getenv("PITWALL_SUBSCRIBER_REVEAL_THRESHOLD", "").strip()
    if raw.isdigit():
        return max(0, int(raw))
    return _DEFAULT_SUBSCRIBER_REVEAL_THRESHOLD


_HOMEPAGE_CSS = """
:root {
  --black: #0A0A0A;
  --white: #F5F2ED;
  --red:   #E10600;
  --teal:  #00D2BE;
  --muted: #8b949e;
  --border:#2A2A2A;
  --mid:   #1C1C1C;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: var(--black);
  color: var(--white);
  font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
  max-width: 720px;
  margin: 0 auto;
  padding: 48px 24px 96px;
  line-height: 1.5;
}
.brand {
  font-size: 13px;
  font-weight: 800;
  letter-spacing: 3px;
  text-transform: uppercase;
  margin-bottom: 48px;
}
.brand span { color: var(--red); }
.hero {
  font-size: clamp(32px, 6vw, 48px);
  font-weight: 900;
  line-height: 1.05;
  letter-spacing: -1px;
  margin-bottom: 16px;
}
.subhero {
  font-size: 15px;
  color: var(--muted);
  margin-bottom: 48px;
  max-width: 520px;
}
.stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 24px;
  margin-bottom: 56px;
  padding: 24px 0;
  border-top: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
}
.stat-label {
  font-size: 9px;
  letter-spacing: 2px;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 6px;
}
.stat-value {
  font-size: clamp(28px, 5vw, 40px);
  font-weight: 800;
  letter-spacing: -1px;
  font-variant-numeric: tabular-nums;
}
.stat-value .pct { color: var(--red); }
.stat-sub { font-size: 11px; color: var(--muted); margin-top: 4px; }
.section { margin-bottom: 40px; }
.section-label {
  font-size: 9px;
  letter-spacing: 2px;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 12px;
}
h2 { font-size: 22px; font-weight: 700; margin-bottom: 12px; }
p { color: #ccc; font-size: 14px; margin-bottom: 12px; }
.cta {
  background: var(--mid);
  border: 1px solid var(--border);
  border-left: 3px solid var(--red);
  padding: 24px;
  margin: 32px 0;
}
.cta-label {
  font-size: 9px;
  letter-spacing: 2px;
  text-transform: uppercase;
  color: var(--red);
  margin-bottom: 8px;
}
.cta-text { font-size: 17px; font-weight: 700; margin-bottom: 6px; }
.cta-sub { font-size: 13px; color: var(--muted); }
.links {
  display: flex;
  gap: 24px;
  flex-wrap: wrap;
  font-size: 13px;
  margin-bottom: 24px;
}
.links a { color: var(--teal); text-decoration: none; }
.links a:hover { text-decoration: underline; }
.footer {
  font-size: 11px;
  color: var(--muted);
  line-height: 1.6;
  border-top: 1px solid var(--border);
  padding-top: 24px;
  margin-top: 48px;
}
"""


_OG = """
<meta property="og:title" content="PitWallAI — F1 fantasy intelligence" />
<meta property="og:description" content="F1 fantasy picks on WhatsApp, scored against actual results. Independent, open source, no app." />
<meta property="og:type" content="website" />
<meta property="og:url" content="https://pitwallai.app/" />
<meta name="twitter:card" content="summary_large_image" />
<meta name="twitter:title" content="PitWallAI — F1 fantasy intelligence" />
<meta name="twitter:description" content="F1 fantasy picks on WhatsApp, scored against actual results." />
"""


def render_homepage_html(stats: dict[str, int | float]) -> str:
    """Render the public homepage with live aggregate numbers.

    `stats` keys: active_subscribers, season_hit_rate_pct, races_scored,
    scored_picks. Cold-start safe — zero values render as "—" or "no
    races scored yet" so we don't ship a misleading 0%.
    """
    subs = int(stats.get("active_subscribers", 0) or 0)
    hit_rate = float(stats.get("season_hit_rate_pct", 0.0) or 0.0)
    races_scored = int(stats.get("races_scored", 0) or 0)
    scored_picks = int(stats.get("scored_picks", 0) or 0)

    hit_rate_html = (
        f'<span class="pct">{hit_rate:.0f}%</span>'
        if scored_picks > 0
        else '<span class="pct">—</span>'
    )
    hit_rate_sub = (
        f"across {scored_picks} scored pick{'s' if scored_picks != 1 else ''}"
        if scored_picks > 0
        else "no races scored yet"
    )

    # Reveal the raw subscriber count only above threshold. Below it,
    # show a qualitative "early access" label so weekly churn noise can't
    # downgrade the public brand. See module docstring.
    reveal_threshold = _subscriber_reveal_threshold()
    if subs >= reveal_threshold:
        subs_html = f"{subs:,}"
        subs_sub = "on WhatsApp"
    elif subs > 0:
        subs_html = "Early"
        subs_sub = "invite-only ramp"
    else:
        subs_html = "—"
        subs_sub = "pre-launch"

    races_html = f"{races_scored}" if races_scored > 0 else "—"
    races_sub = "this season" if races_scored > 0 else "season opens soon"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>PitWallAI — F1 fantasy intelligence on WhatsApp</title>
  <meta name="description" content="Open-source F1 fantasy intelligence. Personalized picks delivered to WhatsApp, scored against actual results every race." />
  {_OG}
  <style>{_HOMEPAGE_CSS}</style>
</head>
<body>
  <div class="brand">Pit<span>Wall</span>AI</div>

  <div class="hero">F1 fantasy intelligence, on WhatsApp.</div>
  <p class="subhero">
    Personalized picks three hours before lock. Scored against actual results every race.
    Open source. No app required.
  </p>

  <div class="stats" aria-label="Live season stats">
    <div>
      <div class="stat-label">Subscribers</div>
      <div class="stat-value">{escape(subs_html)}</div>
      <div class="stat-sub">{escape(subs_sub)}</div>
    </div>
    <div>
      <div class="stat-label">Season GP hit rate</div>
      <div class="stat-value">{hit_rate_html}</div>
      <div class="stat-sub">{escape(hit_rate_sub)}</div>
    </div>
    <div>
      <div class="stat-label">Races scored</div>
      <div class="stat-value">{escape(races_html)}</div>
      <div class="stat-sub">{escape(races_sub)}</div>
    </div>
  </div>

  <div class="cta">
    <div class="cta-label">Get picks on WhatsApp</div>
    <div class="cta-text">Text SUBSCRIBE to start.</div>
    <div class="cta-sub">Free. Reply HELP for commands. UNSUBSCRIBE anytime.</div>
  </div>

  <div class="section">
    <div class="section-label">How it works</div>
    <h2>Three agents across the weekend.</h2>
    <p>
      Thursday context → Friday practice → Saturday quali. Picks land
      three hours before lock — your team, your budget, your transfers.
      Sunday's race monitor logs every strategic call-out with timestamps,
      so you can show your league chat afterward what we saw and when.
    </p>
  </div>

  <div class="section">
    <div class="section-label">What you can look at right now</div>
    <div class="links">
      <a href="/sample">See a sample pick + recap</a>
      <a href="/results">Season hit-rate page</a>
      <a href="https://github.com/whitjenk/pitwallai">Open-source repo</a>
    </div>
  </div>

  <div class="footer">
    PitWallAI is an independent fan project not affiliated with Formula 1,
    F1 Fantasy, ESPN, or any constructor. Picks are informational only.
    Not financial or betting advice.
  </div>
</body>
</html>"""


async def render_homepage_for_request() -> str:
    """Entry point — loads stats and renders."""
    from intelligence.repository import get_public_stats

    stats = await get_public_stats()
    return render_homepage_html(stats)
