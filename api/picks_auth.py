"""Authentication dependency for the picks REST API."""

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, Request, status

from intelligence.picks_config import PicksSettings

_PICKS_API_KEY_HEADER = "X-PitWall-API-Key"


def _api_key_from_request(request: Request, header_key: str | None) -> str:
    if header_key and header_key.strip():
        return header_key.strip()
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def require_picks_api_key(
    request: Request,
    phone: str | None = None,
    x_pitwall_api_key: str | None = Header(default=None, alias=_PICKS_API_KEY_HEADER),
) -> None:
    """
    Enforce API key when personalized picks are requested or when a global key is configured.

    Args:
        request: FastAPI request.
        phone: Optional subscriber phone query parameter.
        x_pitwall_api_key: Shared secret header.

    Raises:
        HTTPException: 401/503 when access is denied.
    """
    settings: PicksSettings = request.app.state.picks_settings
    configured = settings.api_key.strip() if settings.api_key else ""
    provided = _api_key_from_request(request, x_pitwall_api_key)

    if phone:
        if not configured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Personalized picks require PITWALL_PICKS_API_KEY on the server.",
            )
        if not provided or not secrets.compare_digest(provided, configured):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing API key.",
            )
        return

    if configured and (
        not provided or not secrets.compare_digest(provided, configured)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
        )
