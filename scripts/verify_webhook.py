#!/usr/bin/env python3
"""Verify Meta WhatsApp webhook GET handshake.

Usage:
    python scripts/verify_webhook.py --base-url https://your-app.railway.app
    python scripts/verify_webhook.py --base-url http://localhost:8000
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("PITWALL_BASE_URL", "http://127.0.0.1:8000"),
        help="API base URL (no trailing slash)",
    )
    args = parser.parse_args()

    from whatsapp.settings import get_whatsapp_settings

    settings = get_whatsapp_settings()
    token = settings.webhook_verify_token.strip()
    if not token:
        print("❌ WEBHOOK_VERIFY_TOKEN unset")
        return 1

    challenge = "pitwall-verify-test-12345"
    url = (
        f"{args.base_url.rstrip('/')}/webhook"
        f"?hub.mode=subscribe&hub.verify_token={token}&hub.challenge={challenge}"
    )
    try:
        resp = httpx.get(url, timeout=15.0)
    except httpx.HTTPError as exc:
        print(f"❌ Request failed: {exc}")
        return 1

    if resp.status_code == 200 and resp.text.strip() == challenge:
        print(f"✅ Webhook verify OK ({args.base_url})")
        return 0

    print(f"❌ Webhook verify failed status={resp.status_code} body={resp.text[:200]!r}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
