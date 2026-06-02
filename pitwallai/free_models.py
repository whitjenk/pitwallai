"""Free-models-only guardrail.

For early launch / testing we must never call a billed model. This is the
single source of truth for "is this model free?", enforced at the one choke
point every LLM call funnels through (``model_factory.get_model``).

Free paths:
  * Google AI Studio Gemini *flash* models — generous free tier, used via an
    API key with ``PITWALL_LLM_USE_VERTEX=false``.
  * Ollama — local, no API billing.

Billed paths that are blocked when ``PITWALL_FREE_MODELS_ONLY`` is on (default):
  * Vertex AI Gemini (charges the GCP project).
  * OpenAI, Anthropic/Claude.
  * Gemini Pro models (not in the free tier).
"""

from __future__ import annotations

import os

# Local/free providers that never incur API charges.
_LOCAL_FREE_PROVIDERS = frozenset({"ollama"})


class PaidModelBlockedError(RuntimeError):
    """Raised when free-models-only mode would otherwise call a billed model."""


def free_models_only() -> bool:
    """Whether to forbid billed models. Defaults ON so early testing is safe."""
    raw = os.getenv("PITWALL_FREE_MODELS_ONLY", "1").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def is_free_model(
    provider: str,
    model_name: str | None,
    *,
    use_vertex: bool,
    api_key: str,
) -> bool:
    """Return True only when this exact config is known to be free of charge."""
    p = (provider or "").strip().lower()
    if p in _LOCAL_FREE_PROVIDERS:
        return True
    if p == "gemini":
        if use_vertex:
            return False  # Vertex AI bills the GCP project
        if not (api_key or "").strip():
            return False  # AI Studio free tier requires a key
        # Free tier covers the flash family; Pro models are paid.
        return "flash" in (model_name or "").lower()
    return False  # openai, claude, anything else → paid


def assert_free_model(
    provider: str,
    model_name: str | None,
    *,
    use_vertex: bool,
    api_key: str,
) -> None:
    """Raise PaidModelBlockedError when free-only is on and the model is billed."""
    if not free_models_only():
        return
    if is_free_model(provider, model_name, use_vertex=use_vertex, api_key=api_key):
        return
    raise PaidModelBlockedError(
        "PITWALL_FREE_MODELS_ONLY is on — blocked a billed model "
        f"(provider={provider!r}, model={model_name or 'default'!r}, vertex={use_vertex}). "
        "Use free Google AI Studio Gemini flash (set PITWALL_GOOGLE_API_KEY and "
        "PITWALL_LLM_USE_VERTEX=false), or set PITWALL_FREE_MODELS_ONLY=0 to allow paid models."
    )
