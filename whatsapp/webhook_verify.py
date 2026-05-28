"""Meta WhatsApp webhook signature verification helpers."""

from __future__ import annotations

import hashlib
import hmac
import os


def webhook_skip_signature() -> bool:
    """True when local dev explicitly disables signature checks."""
    return os.getenv("PITWALL_WEBHOOK_SKIP_SIGNATURE", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def verify_meta_signature(
    body: bytes,
    signature_header: str | None,
    app_secret: str,
) -> bool:
    """
    Validate X-Hub-Signature-256 per Meta's webhook security docs.

    Args:
        body: Raw POST body bytes.
        signature_header: Value of X-Hub-Signature-256 (sha256=<hex>).
        app_secret: Meta app secret (WHATSAPP_APP_SECRET).

    Returns:
        True when the HMAC matches.
    """
    if not app_secret.strip():
        return False
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected_hex = signature_header.removeprefix("sha256=").strip()
    if not expected_hex:
        return False
    computed = hmac.new(
        app_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(computed, expected_hex)
