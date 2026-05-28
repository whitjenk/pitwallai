"""Tests for Meta webhook signature verification."""

from __future__ import annotations

import hashlib
import hmac

from whatsapp.webhook_verify import (
    is_duplicate_message,
    verify_meta_signature,
)


def _sign(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_verify_meta_signature_valid() -> None:
    body = b'{"entry":[]}'
    secret = "test-app-secret"
    assert verify_meta_signature(body, _sign(body, secret), secret)


def test_verify_meta_signature_rejects_wrong_secret() -> None:
    body = b'{"entry":[]}'
    assert not verify_meta_signature(body, _sign(body, "other"), "test-app-secret")


def test_verify_meta_signature_rejects_missing_header() -> None:
    assert not verify_meta_signature(b"{}", None, "secret")


def test_is_duplicate_message() -> None:
    assert is_duplicate_message("wamid.test-dedup-1") is False
    assert is_duplicate_message("wamid.test-dedup-1") is True
