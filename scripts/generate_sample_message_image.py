#!/usr/bin/env python3
"""Render a WhatsApp-style mockup of a PitWallAI message → docs/sample-message.png.

Used as the README hero and in beta invites. Leads with the "what we called"
receipts message — the artifact that works on race one and is the brand's
primary shareable. Re-run after copy changes:

    python scripts/generate_sample_message_image.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# WhatsApp-ish chrome.
_WA_HEADER = (31, 44, 52)
_WA_BG = (12, 19, 23)
_WA_BUBBLE = (31, 42, 49)
_WA_TEXT = (233, 237, 244)
_WA_MUTED = (138, 149, 158)
_ACCENT = (90, 224, 200)
_ORANGE = (255, 107, 0)

_YELLOW = (255, 196, 0)
_RED = (255, 92, 92)

_W = 820
_PAD = 28

# (text, kind, dot_color) — emoji omitted because the bundled font has no
# emoji glyphs; coloured dots are drawn manually instead.
_MESSAGE = [
    ("Monaco Grand Prix - what we called", "bold", None),
    ("", "body", None),
    ("L34 - Safety car  (14:21:07 UTC)", "body", _YELLOW),
    ("L40 · STR - Retirement  (14:38:55 UTC)", "body", _RED),
    ("L37 · LEC - Pit window  (14:36:02 UTC)", "body", _ORANGE),
    ("", "body", None),
    ("Median decode 1.8s vs source signal", "muted", None),
    ("across 5 call-outs.", "muted", None),
    ("", "body", None),
    ("Full receipts: pitwallai.app/called/…", "link", None),
]


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    # Pillow's bundled default has no separate bold; emulate weight via size bump.
    return ImageFont.load_default(size=size + (2 if bold else 0))


def render() -> Image.Image:
    f_header = _font(26, bold=True)
    f_sub = _font(18)
    fonts = {
        "bold": _font(25, bold=True),
        "body": _font(24),
        "muted": _font(22),
        "link": _font(24),
    }
    colors = {
        "bold": _WA_TEXT,
        "body": _WA_TEXT,
        "muted": _WA_MUTED,
        "link": _ACCENT,
    }

    line_h = 38
    header_h = 96
    bubble_top = header_h + 36
    text_lines = [ln for ln in _MESSAGE]
    bubble_inner_h = len(text_lines) * line_h + 2 * _PAD
    bubble_h = bubble_inner_h + 36  # room for timestamp
    total_h = bubble_top + bubble_h + 40

    img = Image.new("RGB", (_W, total_h), _WA_BG)
    draw = ImageDraw.Draw(img)

    # Header bar.
    draw.rectangle((0, 0, _W, header_h), fill=_WA_HEADER)
    draw.ellipse((24, 22, 76, 74), fill=_ORANGE)
    draw.text((40, 38), "PW", font=f_sub, fill=_WA_BG)
    draw.text((96, 26), "PitWallAI", font=f_header, fill=_WA_TEXT)
    draw.text((96, 60), "online", font=f_sub, fill=_ACCENT)

    # Incoming bubble (left-aligned, white-ish).
    bx0, bx1 = 24, _W - 120
    by0, by1 = bubble_top, bubble_top + bubble_h
    draw.rounded_rectangle((bx0, by0, bx1, by1), radius=18, fill=_WA_BUBBLE)

    dot_x = bx0 + _PAD
    text_x = dot_x + 28
    y = by0 + _PAD
    for text, kind, dot in text_lines:
        if dot is not None:
            cy = y + 13
            draw.ellipse((dot_x, cy, dot_x + 14, cy + 14), fill=dot)
        if text:
            x = text_x if dot is not None else dot_x
            draw.text((x, y), text, font=fonts[kind], fill=colors[kind])
        y += line_h

    # Timestamp.
    ts = "20:54"
    tw = draw.textlength(ts, font=f_sub)
    draw.text((bx1 - _PAD - tw, by1 - 32), ts, font=f_sub, fill=_WA_MUTED)

    return img


def main() -> None:
    out = Path(__file__).resolve().parent.parent / "docs" / "sample-message.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    render().save(out, format="PNG")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
