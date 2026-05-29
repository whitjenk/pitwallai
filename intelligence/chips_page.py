"""Public chip plan share page."""

from __future__ import annotations

from html import escape

from intelligence.chip_planner import ChipPlan, load_chip_plan

_CHIPS_CSS = """
body { margin:0; font-family:system-ui,sans-serif; background:#0b0f14; color:#e8edf4; }
.wrap { max-width:390px; margin:0 auto; padding:16px; }
.card { background:#141a22; border-radius:12px; padding:16px; border:1px solid #2a3441; }
.row { border-top:1px solid #2a3441; padding:10px 0; font-size:13px; }
.HIGH { color:#3fb950; } .MEDIUM { color:#d29922; } .LOW { color:#8b949e; }
.band { font-size:12px; color:#8b949e; margin-top:4px; }
.band-label { font-weight:600; }
.band-label.HIGH { color:#3fb950; }
.band-label.MEDIUM { color:#d29922; }
.band-label.LOW { color:#8b949e; }
"""


def render_chips_share_html(plan: ChipPlan) -> str:
    rows = ""
    for w in plan.windows:
        chips = ", ".join(c.value for c in w.recommended_chips) or "—"
        tier = w.confidence_tier.value
        reasons = "; ".join(w.confidence_reasons[:2]) if w.confidence_reasons else ""
        band = (
            f'<div class="band"><span class="band-label {tier}">{tier} circuit fit</span>'
            f"{' · ' + escape(reasons) if reasons else ''}</div>"
        )
        rows += (
            f'<div class="row"><strong>{escape(w.race_name)}</strong> '
            f'<span class="{w.priority}">{w.priority}</span><br/>'
            f"Chips: {escape(chips)} · {escape(w.reasoning)}"
            f"{band}</div>"
        )
    window_count = len(plan.windows)
    og_title = "PitWallAI · Chip plan"
    og_desc = (
        f"Circuit-informed chip windows for the remaining season — "
        f"{window_count} race{'s' if window_count != 1 else ''} ranked by circuit fit."
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{escape(og_title)}</title>
<meta name="description" content="{escape(og_desc)}" />
<meta property="og:title" content="{escape(og_title)}" />
<meta property="og:description" content="{escape(og_desc)}" />
<meta property="og:type" content="article" />
<meta name="twitter:card" content="summary_large_image" />
<meta name="twitter:title" content="{escape(og_title)}" />
<meta name="twitter:description" content="{escape(og_desc)}" />
<style>{_CHIPS_CSS}</style></head>
<body><main class="wrap"><article class="card">
<h1>Chip plan</h1>{rows}
<div class="row" style="color:#8b949e;font-size:11px">
ℹ️ Windows are ranked on circuit characteristics (tyre deg, overtaking,
weather and safety-car history) and where each race sits in the remaining
calendar — not a points projection. "Circuit fit" is a heuristic guide, not
a probability.
</div>
<div class="row" style="color:#8b949e;font-size:11px">
🔍 Verify in the F1 Fantasy app before lock. Official game rules are authoritative.
</div>
</article></main></body></html>"""


async def render_chips_page_for_token(token: str) -> str | None:
    plan = await load_chip_plan(token)
    if plan is None:
        return None
    return render_chips_share_html(plan)
