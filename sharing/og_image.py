"""Branded Open Graph images (1200×630 PNG) for link unfurls.

Share links (CalledRecap, season recap, homepage) declare
``twitter:card = summary_large_image`` — without an ``og:image`` they unfurl
blank in WhatsApp / iMessage / X, which is fatal for a product whose growth
loop is "forward this to your league chat". These renderers produce a crisp,
on-brand card so the link previews carry the proof.

Pure Pillow, bundled font (``ImageFont.load_default(size=...)``) — no system
fonts, no network, portable on Railway. Rendering must never raise into a
request path; callers fall back to the static brand card on error.
"""

from __future__ import annotations

from functools import lru_cache
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

# Pit-wall palette (shared with the HTML share surfaces).
_BG = (7, 11, 22)            # --pw-bg
_SURFACE = (16, 26, 51)      # --pw-surface-start
_TEXT = (245, 248, 255)      # --pw-text
_MUTED = (169, 182, 211)     # --pw-muted
_ACCENT = (94, 161, 255)     # --pw-accent (brand blue — deliberately not F1 red)
_TEAL = (90, 224, 200)       # --pw-trend-up

_W, _H = 1200, 630
_MARGIN = 80


def _font(size: int) -> ImageFont.FreeTypeFont:
    """Load the bundled scalable default font at ``size`` (Pillow >= 10.1)."""
    return ImageFont.load_default(size=size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    """Greedy word-wrap to ``max_w`` pixels."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_w or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def render_og_png(
    *,
    eyebrow: str,
    headline: str,
    stat_value: str,
    stat_label: str,
    footer: str = "Independent fan tool · Not affiliated with F1 Fantasy",
) -> bytes:
    """Render a branded 1200×630 OG card to PNG bytes."""
    img = Image.new("RGB", (_W, _H), _BG)
    draw = ImageDraw.Draw(img)

    # Surface panel + left accent bar.
    draw.rounded_rectangle((40, 40, _W - 40, _H - 40), radius=28, fill=_SURFACE)
    draw.rectangle((40, 40, 52, _H - 40), fill=_ACCENT)

    f_eyebrow = _font(30)
    f_headline = _font(68)
    f_stat = _font(150)
    f_stat_label = _font(34)
    f_footer = _font(26)

    x = _MARGIN
    # Eyebrow.
    draw.text((x, 86), eyebrow.upper(), font=f_eyebrow, fill=_MUTED)

    # Headline (wrapped, max 2 lines).
    y = 140
    for line in _wrap(draw, headline, f_headline, _W - 2 * _MARGIN)[:2]:
        draw.text((x, y), line, font=f_headline, fill=_TEXT)
        y += 80

    # Hero stat.
    draw.text((x, 330), stat_value, font=f_stat, fill=_TEAL)
    stat_w = draw.textlength(stat_value, font=f_stat)
    draw.text((x + stat_w + 24, 430), stat_label, font=f_stat_label, fill=_MUTED)

    # Footer.
    draw.text((x, _H - 96), footer, font=f_footer, fill=_MUTED)

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@lru_cache(maxsize=1)
def brand_og_png() -> bytes:
    """Static brand card for the homepage, sample, and results surfaces."""
    return render_og_png(
        eyebrow="PitWallAI",
        headline="F1 fantasy intelligence, on WhatsApp.",
        stat_value="Receipts",
        stat_label="for your league chat,\nscored against real results",
        footer="Open source · Independent fan tool · Not affiliated with F1 Fantasy",
    )


def called_recap_og_png(recap) -> bytes:  # noqa: ANN001 — CalledRaceRecap (avoid import cycle)
    """Per-race 'what we called' card — leads with the receipts count."""
    count = recap.moment_count
    if count <= 0:
        stat_value, stat_label = "0", "strategic moments\n— a clean race is a verdict"
    else:
        median = recap.median_decode_latency_seconds
        stat_value = str(count)
        label = f"call-out{'s' if count != 1 else ''} logged"
        if median is not None:
            label += f"\nmedian decode {median:.1f}s vs source signal"
        stat_label = label
    return render_og_png(
        eyebrow="PitWallAI · What we called",
        headline=f"{recap.race_label}",
        stat_value=stat_value,
        stat_label=stat_label,
    )


def season_og_png(recap) -> bytes:  # noqa: ANN001 — SeasonRecap (avoid import cycle)
    """Season recap card — your GP hit rate vs the community."""
    vs = int(round(recap.personalized_accuracy_pct - recap.community_accuracy_pct))
    vs_str = f"+{vs}" if vs > 0 else (str(vs) if vs < 0 else "even")
    return render_og_png(
        eyebrow=f"PitWallAI · Season Recap {recap.season}",
        headline="Season complete.",
        stat_value=f"{recap.personalized_accuracy_pct:.0f}%",
        stat_label=f"your GP pick hit rate (race results)\n{vs_str} vs community",
    )
