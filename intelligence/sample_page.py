"""Public `/sample` preview — shows a curious visitor what they'd get.

Three artifacts side by side: WhatsApp pick message, race recap card,
"what we called" card. All mocked from realistic-but-fake data. Labeled
SAMPLE so it's never mistaken for live output.
"""

from __future__ import annotations

_CSS = """
:root {
  --black: #0A0A0A;
  --white: #F5F2ED;
  --red:   #E10600;
  --teal:  #00D2BE;
  --muted: #8b949e;
  --border:#2A2A2A;
  --mid:   #1C1C1C;
  --card:  #141a22;
  --accent:#ff6b00;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: var(--black);
  color: var(--white);
  font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
  max-width: 960px;
  margin: 0 auto;
  padding: 48px 24px 96px;
  line-height: 1.5;
}
.brand {
  font-size: 13px;
  font-weight: 800;
  letter-spacing: 3px;
  text-transform: uppercase;
  margin-bottom: 24px;
}
.brand span { color: var(--red); }
.brand a { color: var(--white); text-decoration: none; }
h1 {
  font-size: clamp(28px, 4vw, 40px);
  font-weight: 900;
  letter-spacing: -1px;
  margin-bottom: 8px;
}
.lede { color: var(--muted); font-size: 15px; margin-bottom: 8px; max-width: 640px; }
.sample-flag {
  display: inline-block;
  background: var(--mid);
  border: 1px solid var(--border);
  color: var(--accent);
  font-size: 10px;
  letter-spacing: 2px;
  text-transform: uppercase;
  padding: 4px 8px;
  margin-bottom: 32px;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 24px;
  margin-bottom: 48px;
}
.col-label {
  font-size: 9px;
  letter-spacing: 2px;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 10px;
}
.whatsapp {
  background: #0e1b14;
  border: 1px solid #1f3a2a;
  border-radius: 12px;
  padding: 16px;
  font-family: ui-monospace, SFMono-Regular, monospace;
  font-size: 13px;
  line-height: 1.55;
  white-space: pre-wrap;
  color: #d4e8d8;
}
.card {
  background: var(--card);
  border: 1px solid #2a3441;
  border-radius: 16px;
  padding: 18px;
}
.eyebrow {
  font-size: 11px; letter-spacing: .08em; text-transform: uppercase;
  color: var(--muted);
}
.card h3 { font-size: 18px; margin: 6px 0 4px; }
.badge {
  display: inline-block; background: #1c2a3a; border-radius: 999px;
  padding: 5px 10px; font-size: 12px; margin: 6px 0 14px; color: var(--white);
}
.row { border-top: 1px solid #2a3441; padding: 10px 0; font-size: 13px; }
.row .lap { color: var(--accent); font-weight: 600; }
.row .who { color: var(--white); font-weight: 600; }
.row .desc { color: #c9d1d9; margin-top: 2px; }
.row .ts { color: var(--muted); font-size: 11px; margin-top: 4px; font-variant-numeric: tabular-nums; }
.pick { border-top: 1px solid #2a3441; padding: 10px 0; font-size: 13px; }
.pick strong { color: var(--accent); }
.ok { color: #3fb950; }
.miss { color: #d29922; }
.stat { font-size: 12px; color: var(--muted); margin-top: 4px; }
.back {
  display: inline-block;
  margin-top: 24px;
  font-size: 13px;
  color: var(--teal);
  text-decoration: none;
}
.back:hover { text-decoration: underline; }
.footer {
  font-size: 11px; color: var(--muted); line-height: 1.6;
  border-top: 1px solid var(--border); padding-top: 24px; margin-top: 48px;
}
"""

_WHATSAPP_SAMPLE = """🏁 *Spanish GP — picks*

*VER* → high conviction
Pole + clean tire window. P1 ceiling +18 pts.

*HAM → ALO* (swap)
ALO 0.4s off pace on hards in FP2.
Predicted Δ: +9 pts. Confidence 78%.

🎴 Chip note
Hold Limitless — Monaco next week is a better circuit fit.

──────────────────
PitWallAI · Not financial advice"""


def render_sample_page() -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>PitWallAI · Sample picks &amp; recap</title>
  <meta name="description" content="Sample of a PitWallAI WhatsApp pick message, race recap card, and live race call-outs." />
  <meta property="og:title" content="PitWallAI · Sample picks &amp; recap" />
  <meta property="og:description" content="What a weekend on PitWallAI looks like — picks, recap, live call-outs." />
  <meta property="og:type" content="website" />
  <meta property="og:image" content="https://pitwallai.app/og/brand.png" />
  <meta property="og:image:width" content="1200" />
  <meta property="og:image:height" content="630" />
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="PitWallAI · Sample picks &amp; recap" />
  <meta name="twitter:image" content="https://pitwallai.app/og/brand.png" />
  <style>{_CSS}</style>
</head>
<body>
  <div class="brand"><a href="/">Pit<span>Wall</span>AI</a></div>
  <div class="sample-flag">Sample · not live data</div>
  <h1>What a weekend on PitWallAI looks like.</h1>
  <p class="lede">
    Three artifacts: the WhatsApp pick message you get before lock,
    the race recap card you can share Sunday night, and the live
    race call-outs your league chat sees you post.
  </p>

  <div class="grid">
    <div>
      <div class="col-label">WhatsApp pick message</div>
      <div class="whatsapp">{_WHATSAPP_SAMPLE}</div>
    </div>

    <div>
      <div class="col-label">Race recap card</div>
      <article class="card">
        <div class="eyebrow">PitWallAI · Race recap</div>
        <h3>Spanish Grand Prix</h3>
        <div class="badge">3/4 picks · 75%</div>
        <div class="stat">Season GP hit rate: 64%</div>
        <div class="pick">
          <span class="ok">✅</span> <strong>HAM → ALO</strong> (+11 pts)
          <div class="stat">ALO 0.4s off pace FP2 hards — predicted +9, actual +11.</div>
        </div>
        <div class="pick">
          <span class="ok">✅</span> <strong>VER</strong> (+18 pts)
          <div class="stat">Pole converted; clean tire window held.</div>
        </div>
        <div class="pick">
          <span class="ok">✅</span> <strong>NOR</strong> (+8 pts)
          <div class="stat">Quietly strong long-run pace in FP2.</div>
        </div>
        <div class="pick">
          <span class="miss">❌</span> <strong>RUS</strong> (-3 pts)
          <div class="stat">Predicted P5 floor; collected debris lap 12.</div>
        </div>
      </article>
    </div>

    <div>
      <div class="col-label">Live race call-outs</div>
      <article class="card">
        <div class="eyebrow">PitWallAI · What we called</div>
        <h3>Spanish Grand Prix</h3>
        <div class="badge">3 call-outs · median pipeline 4.1s</div>
        <div class="row">
          <div>🟡 <span class="lap">L23</span> <span class="who">Safety car</span></div>
          <div class="desc">SC deployed turn 7 — debris from front wing contact.</div>
          <div class="ts">Source signal 14:32:08 UTC · decoded 14:32:12 UTC · pipeline 4.0s</div>
        </div>
        <div class="row">
          <div>🏳️ <span class="lap">L41</span> · GAS <span class="who">Retirement</span></div>
          <div class="desc">PU shutdown reported on team radio.</div>
          <div class="ts">Source signal 14:51:33 UTC · decoded 14:51:37 UTC · pipeline 4.2s</div>
        </div>
        <div class="row">
          <div>⚡ <span class="lap">L48</span> · LEC <span class="who">Pit window</span></div>
          <div class="desc">Undercut activated — fresh hards 18 laps to go.</div>
          <div class="ts">Source signal 14:58:01 UTC · decoded 14:58:05 UTC · pipeline 4.1s</div>
        </div>
      </article>
    </div>
  </div>

  <a class="back" href="/">← Back to homepage</a>

  <div class="footer">
    PitWallAI is an independent fan project not affiliated with Formula 1,
    F1 Fantasy, ESPN, or any constructor. Picks are informational only.
    Not financial or betting advice.
  </div>
</body>
</html>"""
