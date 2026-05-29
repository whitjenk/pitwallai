#!/usr/bin/env python3
"""
Generate /results static HTML from scored pick data.

Run after each race scoring job completes.

Usage:
    python scripts/generate_results_page.py
    python scripts/generate_results_page.py --output /path/to/output.html
    python scripts/generate_results_page.py --season 2026
"""

from __future__ import annotations

import argparse
import asyncio
import html
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT_PATH = PROJECT_ROOT / "api" / "static" / "results.html"
WA_NUMBER = os.getenv("WHATSAPP_DISPLAY_NUMBER", "")


def _wa_me_href(prefill: str = "SUBSCRIBE") -> str:
    """Build wa.me click-to-chat link; empty when number is unset."""
    from urllib.parse import quote

    digits = "".join(ch for ch in WA_NUMBER if ch.isdigit())
    if not digits:
        return ""
    return f"https://wa.me/{digits}?text={quote(prefill)}"


def _cta_block(label: str = "Get picks on WhatsApp") -> str:
    """One-tap acquisition: wa.me button opens WhatsApp with SUBSCRIBE pre-typed."""
    href = _wa_me_href("SUBSCRIBE")
    pretty_number = _esc(WA_NUMBER) if WA_NUMBER else "WhatsApp"
    if href:
        return f"""
  <div class="cta">
    <div class="cta-label">{_esc(label)}</div>
    <a class="cta-btn" href="{_esc(href)}">Chat with PitWallAI →</a>
    <div class="cta-sub">Tap to open WhatsApp · or text SUBSCRIBE to {pretty_number}</div>
  </div>"""
    return f"""
  <div class="cta">
    <div class="cta-label">{_esc(label)}</div>
    <div class="cta-text">Text SUBSCRIBE to {pretty_number}</div>
    <div class="cta-sub">Free. No app required. Reply HELP for commands.</div>
  </div>"""


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def results_body(stats) -> str:
    rows = ""
    for r in stats.results:
        icon = "✓" if r.was_correct else "✗"
        cls = "correct" if r.was_correct else "wrong"
        rows += f"""
      <tr>
        <td>{_esc(r.race_name)}</td>
        <td>{_esc(r.pick_driver)}</td>
        <td>{_esc(r.actual_top_scorer)}</td>
        <td>{r.fantasy_points:+.0f} pts</td>
        <td class="{cls}">{icon}</td>
      </tr>"""

    filled = round(stats.hit_rate_pct / 10)
    bar = "█" * filled + "░" * (10 - filled)

    return f"""
  <div class="headline">
    <span class="pct">{stats.hit_rate_pct:.0f}%</span>
  </div>
  <div class="subhead">Pick accuracy · {stats.season} season · {bar}</div>
  <div class="stat-row">
    <div class="stat">
      <div class="stat-label">Races scored</div>
      <div class="stat-value">{stats.races_scored}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Correct picks</div>
      <div class="stat-value">{stats.correct_picks}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Best race</div>
      <div class="stat-value">{_esc(stats.best_race_name)}</div>
    </div>
  </div>

  <table>
    <thead>
      <tr>
        <th>Race</th>
        <th>Pick</th>
        <th>Actual</th>
        <th>Points</th>
        <th>Result</th>
      </tr>
    </thead>
    <tbody>{rows}
    </tbody>
  </table>

  {_cta_block()}"""


def no_data_body(season: int) -> str:
    return f"""
  <div class="headline"><span class="pct">—</span></div>
  <div class="subhead">Season {season} · No races scored yet</div>
  <p style="color:var(--muted);font-size:14px;margin-bottom:48px">
    Pick accuracy is published after each race. Check back after Race 1.
  </p>
  {_cta_block()}"""


def calibration_body(calibration) -> str:
    """Render the per-band calibration block.

    The brand-defining "we publish how often our HIGH calls actually hit"
    panel. Hidden when there's no scored data yet (caller passes None).
    """
    if not calibration:
        return ""
    rows = ""
    for band in calibration:
        if band.sample_size == 0:
            continue
        actual = f"{band.hit_rate * 100:.0f}%"
        target = f"{band.target_hit_rate * 100:.0f}%"
        drift_pp = band.drift * 100
        if abs(drift_pp) <= 5:
            badge_class, badge_text = "drift-ok", "calibrated"
        elif drift_pp > 0:
            badge_class, badge_text = "drift-up", f"+{drift_pp:.0f}pp"
        else:
            badge_class, badge_text = "drift-down", f"{drift_pp:.0f}pp"
        rows += f"""
      <tr>
        <td><span class="band band-{band.band.value.lower()}">{band.band.value}</span></td>
        <td>{actual}</td>
        <td>{target}</td>
        <td><span class="cal-badge {badge_class}">{badge_text}</span></td>
        <td>{band.sample_size}</td>
      </tr>"""
    if not rows:
        return ""
    return f"""
  <h2 class="section-h">Calibration · {len(calibration)} bands</h2>
  <p class="section-sub">
    When PitWallAI says HIGH, it should hit at ≥70%. Here's what it actually did.
    Drift past ±5pp triggers a recalibration check.
  </p>
  <table class="cal-table">
    <thead>
      <tr>
        <th>Band</th>
        <th>Hit rate</th>
        <th>Target</th>
        <th>Status</th>
        <th>N</th>
      </tr>
    </thead>
    <tbody>{rows}
    </tbody>
  </table>"""


def render_html(stats, *, season: int, calibration=None) -> str:
    updated = datetime.now(tz=UTC).strftime("%d %b %Y, %H:%M UTC")
    body = no_data_body(season) if not stats or stats.races_scored == 0 else results_body(stats)
    cal_block = calibration_body(calibration)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PitWallAI · Season Results {season}</title>
  <style>
    :root {{
      --black: #0A0A0A;
      --white: #F5F2ED;
      --red:   #E10600;
      --teal:  #00D2BE;
      --amber: #FF8700;
      --mid:   #1C1C1C;
      --border:#2A2A2A;
      --muted: #666;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: var(--black);
      color: var(--white);
      font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
      max-width: 720px;
      margin: 0 auto;
      padding: 40px 24px 80px;
    }}
    .brand {{
      font-size: 13px;
      font-weight: 800;
      letter-spacing: 3px;
      text-transform: uppercase;
      margin-bottom: 40px;
    }}
    .brand span {{ color: var(--red); }}
    .headline {{
      font-size: clamp(56px, 12vw, 96px);
      font-weight: 900;
      line-height: 0.9;
      letter-spacing: -2px;
      margin-bottom: 8px;
    }}
    .headline .pct {{ color: var(--red); }}
    .subhead {{
      font-size: 13px;
      color: var(--muted);
      letter-spacing: 2px;
      text-transform: uppercase;
      margin-bottom: 48px;
    }}
    .stat-row {{
      display: flex;
      gap: 32px;
      margin-bottom: 48px;
      flex-wrap: wrap;
    }}
    .stat-label {{
      font-size: 9px;
      letter-spacing: 2px;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 4px;
    }}
    .stat-value {{
      font-size: 22px;
      font-weight: 700;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin-bottom: 48px;
      font-size: 13px;
    }}
    th {{
      font-size: 9px;
      letter-spacing: 2px;
      text-transform: uppercase;
      color: var(--muted);
      text-align: left;
      padding: 8px 0;
      border-bottom: 1px solid var(--border);
    }}
    td {{
      padding: 12px 0;
      border-bottom: 1px solid var(--border);
      color: #ccc;
      vertical-align: top;
    }}
    td:first-child {{ color: var(--white); font-weight: 600; }}
    .correct {{ color: var(--teal); font-weight: 700; }}
    .wrong   {{ color: var(--muted); }}
    .cta {{
      background: var(--mid);
      border: 1px solid var(--border);
      border-left: 3px solid var(--red);
      padding: 20px 24px;
      margin-bottom: 40px;
    }}
    .cta-label {{
      font-size: 9px;
      letter-spacing: 2px;
      text-transform: uppercase;
      color: var(--red);
      margin-bottom: 8px;
    }}
    .cta-text {{
      font-size: 15px;
      font-weight: 600;
      margin-bottom: 4px;
    }}
    .cta-btn {{
      display: inline-block;
      background: #25D366;
      color: #0A0A0A;
      font-weight: 700;
      font-size: 15px;
      letter-spacing: 0.5px;
      padding: 12px 20px;
      margin-bottom: 8px;
      text-decoration: none;
      border-radius: 4px;
    }}
    .cta-btn:hover {{ background: #1ebb59; }}
    .cta-sub {{ font-size: 12px; color: var(--muted); }}
    .updated {{
      font-size: 11px;
      color: var(--muted);
      letter-spacing: 1px;
    }}
    .disclaimer {{
      font-size: 11px;
      color: var(--border);
      margin-top: 16px;
      line-height: 1.6;
    }}
    .section-h {{
      font-size: 18px;
      font-weight: 800;
      letter-spacing: 1px;
      text-transform: uppercase;
      margin-top: 48px;
      margin-bottom: 8px;
    }}
    .section-sub {{
      font-size: 13px;
      color: var(--muted);
      margin-bottom: 16px;
      line-height: 1.5;
    }}
    .cal-table th {{ font-size: 10px; }}
    .cal-table td {{ font-size: 13px; padding: 10px 6px; }}
    .band {{
      display: inline-block;
      font-size: 10px;
      font-weight: 800;
      letter-spacing: 1.5px;
      padding: 3px 8px;
      border-radius: 3px;
    }}
    .band-high {{ background: var(--red); color: var(--white); }}
    .band-med  {{ background: var(--amber); color: var(--black); }}
    .band-low  {{ background: var(--mid); color: var(--white); border: 1px solid var(--border); }}
    .cal-badge {{
      display: inline-block;
      font-size: 10px;
      letter-spacing: 1px;
      padding: 3px 7px;
      border-radius: 3px;
    }}
    .drift-ok   {{ background: var(--teal); color: var(--black); }}
    .drift-up   {{ background: var(--mid); color: var(--teal); border: 1px solid var(--teal); }}
    .drift-down {{ background: var(--mid); color: var(--amber); border: 1px solid var(--amber); }}
  </style>
</head>
<body>
  <div class="brand">Pit<span>Wall</span>AI</div>
  {body}
  {cal_block}
  <div class="updated">Last updated: {updated}</div>
  <div class="disclaimer">
    PitWallAI is an independent fan project not affiliated with Formula 1,
    F1 Fantasy, ESPN, or any constructor. Picks are informational only.
    Not financial or betting advice.
  </div>
</body>
</html>"""


async def _load_calibration(season: int):
    """Return calibration report list, or None when no scored picks exist yet."""
    from intelligence.eval.calibration import calibration_report
    from intelligence.repository import get_session
    from db.models import PickRow
    from sqlalchemy import select

    async with get_session() as session:
        result = await session.execute(
            select(PickRow).where(
                PickRow.race_key.like(f"{season}_%"),
                PickRow.was_correct.is_not(None),
            )
        )
        picks = list(result.scalars().all())
    if not picks:
        return None
    return calibration_report(picks)


async def generate(output_path: Path, season: int) -> None:
    from db.scorer import get_season_accuracy

    stats = await get_season_accuracy(season=season)
    try:
        calibration = await _load_calibration(season)
    except Exception:
        calibration = None
    page = render_html(stats, season=season, calibration=calibration)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(page, encoding="utf-8")
    print(f"Generated: {output_path} ({len(page)} bytes)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate PitWallAI public results HTML")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--season", type=int, default=2026)
    args = parser.parse_args()
    asyncio.run(generate(output_path=args.output, season=args.season))


if __name__ == "__main__":
    main()
