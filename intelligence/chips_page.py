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
"""


def render_chips_share_html(plan: ChipPlan) -> str:
    rows = ""
    for w in plan.windows:
        chips = ", ".join(c.value for c in w.recommended_chips) or "—"
        rows += (
            f'<div class="row"><strong>{escape(w.race_name)}</strong> '
            f'<span class="{w.priority}">{w.priority}</span><br/>'
            f"Chips: {escape(chips)} · {escape(w.reasoning)}</div>"
        )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>PitWallAI chip plan</title><style>{_CHIPS_CSS}</style></head>
<body><main class="wrap"><article class="card">
<h1>Chip plan</h1>{rows}
</article></main></body></html>"""


async def render_chips_page_for_token(token: str) -> str | None:
    plan = await load_chip_plan(token)
    if plan is None:
        return None
    return render_chips_share_html(plan)
