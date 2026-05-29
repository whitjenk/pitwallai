#!/usr/bin/env python3
"""
Generate a QR code for the PitWallAI WhatsApp click-to-chat link.

Drop the PNG on posters, Discord embeds, video end-cards, paddock flyers.
Scan with phone camera → WhatsApp opens with SUBSCRIBE pre-typed.

Usage:
    python scripts/generate_subscribe_qr.py
    python scripts/generate_subscribe_qr.py --out subscribe.png
    python scripts/generate_subscribe_qr.py --prefill "PICKS"
    python scripts/generate_subscribe_qr.py --number +15551234567

Reads WHATSAPP_DISPLAY_NUMBER from env unless --number is passed.
Requires the `qrcode` package: pip install qrcode[pil]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import quote


def _digits_only(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def build_wa_me(number: str, prefill: str) -> str:
    digits = _digits_only(number)
    if not digits:
        raise SystemExit(
            "No WhatsApp number set. Pass --number or set WHATSAPP_DISPLAY_NUMBER."
        )
    return f"https://wa.me/{digits}?text={quote(prefill)}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--number",
        default=os.getenv("WHATSAPP_DISPLAY_NUMBER", ""),
        help="WhatsApp display number (E.164 or digits). Defaults to env.",
    )
    parser.add_argument(
        "--prefill",
        default="SUBSCRIBE",
        help="Message pre-typed in the user's WhatsApp composer (default: SUBSCRIBE).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("subscribe_qr.png"),
        help="Output PNG path (default: ./subscribe_qr.png).",
    )
    parser.add_argument(
        "--box-size",
        type=int,
        default=12,
        help="QR module pixel size — bigger = larger PNG (default: 12).",
    )
    args = parser.parse_args()

    url = build_wa_me(args.number, args.prefill)

    try:
        import qrcode
    except ImportError:
        print(
            "Missing dependency: qrcode. Install with:\n"
            "    pip install 'qrcode[pil]'",
            file=sys.stderr,
        )
        return 1

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=args.box_size,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0A0A0A", back_color="#F5F2ED")
    img.save(args.out)
    print(f"Wrote {args.out}  ·  {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
