"""Fernet encryption for subscriber API keys at rest."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from whatsapp.settings import get_whatsapp_settings


def _fernet() -> Fernet:
    """
    Build a Fernet instance from ENCRYPTION_KEY.

    Returns:
        Fernet cipher.

    Raises:
        ValueError: If ENCRYPTION_KEY is missing or invalid.
    """
    key = get_whatsapp_settings().encryption_key.strip()
    if not key:
        raise ValueError("ENCRYPTION_KEY is not configured")
    try:
        return Fernet(key.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise ValueError("ENCRYPTION_KEY must be a valid Fernet key") from exc


def encrypt_api_key(plaintext: str) -> str:
    """
    Encrypt a user API key for database storage.

    Args:
        plaintext: Raw API key.

    Returns:
        Fernet token as a UTF-8 string.
    """
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_api_key(ciphertext: str) -> str:
    """
    Decrypt a stored API key.

    Args:
        ciphertext: Fernet token string from the database.

    Returns:
        Plaintext API key.

    Raises:
        ValueError: On invalid ciphertext or missing encryption key.
    """
    try:
        return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Invalid encrypted API key") from exc
