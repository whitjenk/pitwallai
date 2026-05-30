"""Public share page for the post-race 'we called it' recap.

Screenshot-friendly, no PII. Mobile-width — designed to be screencapped
straight into a group chat. Each row is its own piece of evidence: lap,
event, source-signal timestamp, our decode timestamp.
"""

from __future__ import annotations

from html import escape

from intelligence.called_recap import CalledRaceRecap, load_called_recap

_CSS = """
body { margin:0; font-family:system-ui,-apple-system,sans-serif;
       background:#0b0f14; color:#e8edf4; }
.wrap { max-width:390px; margin:0 auto; padding:20px 16px 32px; }
.card { background:#141a22; border-radius:16px; padding:20px;
        border:1px solid #2a3441; }
.eyebrow { font-size:11px; letter-spacing:.08em; text-transform:uppercase;
           color:#8b949e; }
h1 { font-size:22px; margin:8px 0 4px; }
.badge { display:inline-block; background:#1c2a3a; border-radius:999px;
         padding:6px 12px; font-size:13px; margin:8px 0 16px; color:#e8edf4; }
.row { border-top:1px solid #2a3441; padding:12px 0; font-size:14px; }
.row .lap { color:#ff6b00; font-weight:600; }
.row .who { color:#e8edf4; font-weight:600; }
.row .desc { color:#c9d1d9; margin-top:2px; }
.row .ts { color:#8b949e; font-size:12px; margin-top:4px; font-variant-numeric: tabular-nums; }
.empty { color:#8b949e; padding:12px 0; font-size:14px; }
.cta { margin-top:20px; text-align:center; font-size:13px; color:#8b949e; }
.cta a { color:#ff6b00; }
.note { margin-top:14px; font-size:11px; color:#8b949e; line-height:1.4; }
"""

_GLYPH = {
    "SAFETY_CAR": "🟡",
    "VIRTUAL_SC": "🟡",
    "RED_FLAG": "🔴",
    "RETIREMENT": "🏳️",
    "PIT_WINDOW_OPEN": "⚡",
}

_LABEL = {
    "SAFETY_CAR": "Safety car",
    "VIRTUAL_SC": "VSC",
    "RED_FLAG": "Red flag",
    "RETIREMENT": "Retirement",
    "PIT_WINDOW_OPEN": "Pit window",
}


def render_called_recap_share_html(recap: CalledRaceRecap) -> str:
    og_image = f"https://pitwallai.app/og/called/{escape(recap.share_token)}.png"
    rows = ""
    for m in recap.moments:
        glyph = _GLYPH.get(m.event_type.value, "·")
        label = _LABEL.get(m.event_type.value, m.event_type.value)
        lap = f"L{m.lap}" if m.lap is not None else "—"
        who = f" · {escape(m.driver_code)}" if m.driver_code else ""
        src = m.source_signal_utc.strftime("%H:%M:%S")
        dec = m.decoded_at_utc.strftime("%H:%M:%S") if m.decoded_at_utc else "—"
        latency = (
            f" · pipeline {m.decode_latency_seconds:.1f}s"
            if m.decode_latency_seconds is not None
            else ""
        )
        rows += (
            f'<div class="row">'
            f'<div>{glyph} <span class="lap">{lap}</span>{who} '
            f"<span class=\"who\">{escape(label)}</span></div>"
            f'<div class="desc">{escape(m.description[:140])}</div>'
            f'<div class="ts">Source signal {src} UTC · decoded {dec} UTC{escape(latency)}</div>'
            f"</div>"
        )
    if not rows:
        if recap.data_unavailable:
            rows = (
                '<div class="empty">'
                "OpenF1 was unreachable during the race — PitWallAI could not "
                "log strategic moments. This is not a quiet-race verdict."
                "</div>"
            )
        else:
            rows = (
                '<div class="empty">'
                "PitWallAI counts the moments that mattered. "
                "This weekend, none cleared the bar — a clean processional race "
                "is a verdict, not an absence."
                "</div>"
            )

    median = recap.median_decode_latency_seconds
    median_badge = (
        f"{recap.moment_count} call-out{'s' if recap.moment_count != 1 else ''} "
        f"· median pipeline {median:.1f}s"
        if median is not None
        else f"{recap.moment_count} call-out{'s' if recap.moment_count != 1 else ''}"
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>PitWallAI · {escape(recap.race_label)} — what we called</title>
  <meta name="description" content="{escape(median_badge)} during {escape(recap.race_label)}." />
  <meta property="og:title" content="PitWallAI · {escape(recap.race_label)} — what we called" />
  <meta property="og:description" content="{escape(median_badge)} — strategic call-outs with source-signal and decode timestamps." />
  <meta property="og:type" content="article" />
  <meta property="og:image" content="{og_image}" />
  <meta property="og:image:width" content="1200" />
  <meta property="og:image:height" content="630" />
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="PitWallAI · {escape(recap.race_label)} — what we called" />
  <meta name="twitter:description" content="{escape(median_badge)} during {escape(recap.race_label)}." />
  <meta name="twitter:image" content="{og_image}" />
  <style>{_CSS}</style>
</head>
<body>
  <main class="wrap">
    <article class="card">
      <div class="eyebrow">PitWallAI · What we called</div>
      <h1>{escape(recap.race_label)}</h1>
      <div class="badge">{median_badge}</div>
      {rows}
      <div class="note">
        Timestamps are source-signal time (OpenF1 race control) and PitWallAI decode time.
        Compare against your memory of the broadcast.
      </div>
      <div class="cta">Subscribe at <a href="https://pitwallai.app">pitwallai.app</a></div>
    </article>
  </main>
</body>
</html>"""


async def render_called_recap_page_for_token(share_token: str) -> str | None:
    recap = await load_called_recap(share_token)
    if recap is None:
        return None
    return render_called_recap_share_html(recap)
