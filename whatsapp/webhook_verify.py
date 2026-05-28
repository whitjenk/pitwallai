"""Meta WhatsApp webhook signature verification and inbound deduplication."""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from collections import OrderedDict

# message_id → monotonic expiry (dedup window)
_SEEN_MESSAGE_IDS: OrderedDict[str, float] = OrderedDict()
_DEDUP_MAX_ENTRIES = 50_000
_DEDUP_TTL_SECONDS = 86_400  # 24h — Meta may retry webhooks


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


def _prune_seen_ids(now: float) -> None:
    while _SEEN_MESSAGE_IDS:
        oldest_id, oldest_exp = next(iter(_SEEN_MESSAGE_IDS.items()))
        if oldest_exp > now and len(_SEEN_MESSAGE_IDS) <= _DEDUP_MAX_ENTRIES:
            break
        _SEEN_MESSAGE_IDS.pop(oldest_id, None)
    while len(_SEEN_MESSAGE_IDS) > _DEDUP_MAX_ENTRIES:
        _SEEN_MESSAGE_IDS.popitem(last=False)


def is_duplicate_message(message_id: str) -> bool:
    """
    Return True if this Meta message_id was already processed.

    Args:
        message_id: Meta message id from the webhook payload.

    Returns:
        True when the message should be skipped (replay).
    """
    if not message_id.strip():
        return False
    now = time.monotonic()
    _prune_seen_ids(now)
    if message_id in _SEEN_MESSAGE_IDS:
        return True
    _SEEN_MESSAGE_IDS[message_id] = now + _DEDUP_TTL_SECONDS
    return False
