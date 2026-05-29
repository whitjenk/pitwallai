"""Production launch configuration checks — fail loud in live mode."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from whatsapp.settings import get_whatsapp_settings
from whatsapp.webhook_verify import webhook_skip_signature


@dataclass
class LaunchCheckResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate_launch_config(*, mode: str) -> LaunchCheckResult:
    """Validate env for the given runtime mode."""
    result = LaunchCheckResult(ok=True)
    settings = get_whatsapp_settings()
    mode_l = mode.strip().lower()

    if mode_l == "live":
        required = {
            "DATABASE_URL": settings.database_url.strip(),
            "WHATSAPP_TOKEN": settings.whatsapp_token.strip(),
            "WHATSAPP_PHONE_NUMBER_ID": settings.whatsapp_phone_number_id.strip(),
            "WEBHOOK_VERIFY_TOKEN": settings.webhook_verify_token.strip(),
            "WHATSAPP_APP_SECRET": settings.whatsapp_app_secret.strip(),
            "WHATSAPP_DISPLAY_NUMBER": settings.display_number.strip(),
        }
        for name, value in required.items():
            if not value:
                result.errors.append(f"{name} is required when PITWALL_MODE=live")
        if webhook_skip_signature() and mode_l == "live":
            result.errors.append(
                "PITWALL_DEV_ONLY_SKIP_WEBHOOK_SIGNATURE must be unset in live mode"
            )
        if not os.getenv("PITWALL_PRICES_VERIFIED", "").strip():
            result.warnings.append(
                "PITWALL_PRICES_VERIFIED is not set — transfer swap picks are disabled "
                "(generic driver picks only until you verify fantasy/prices.json)"
            )
    elif not settings.database_url.strip():
        result.warnings.append("DATABASE_URL unset — subscriber features disabled")

    if result.errors:
        result.ok = False
    return result


def assert_live_ready(*, mode: str) -> None:
    """Raise RuntimeError when live mode config is incomplete."""
    check = validate_launch_config(mode=mode)
    for warning in check.warnings:
        from loguru import logger

        logger.warning("Launch check: {}", warning)
    if not check.ok:
        msg = "Live launch configuration invalid:\n" + "\n".join(
            f"  - {e}" for e in check.errors
        )
        raise RuntimeError(msg)
