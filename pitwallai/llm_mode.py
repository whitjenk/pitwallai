"""LLM mode: 'free' (rules only, no LLM) vs 'byo' (bring your own provider).

PitWallAI ships in two modes:

  * free  — the default. No LLM is ever called; every tip is deterministic
    rules over live data. $0, no keys, nothing to configure.
  * byo   — bring your own LLM. The deterministic numbers are unchanged; an
    LLM only adds richer natural-language prose on top (an "insight" layer).
    Pick any provider supported by the model factory:
        ollama  — local, free, no key (great for testing): PITWALL_LLM_PROVIDER=ollama
        claude  — needs ANTHROPIC_API_KEY + PITWALL_FREE_MODELS_ONLY=0
        gemini  — free AI Studio flash key, or Vertex
        openai  — needs OPENAI_API_KEY + PITWALL_FREE_MODELS_ONLY=0

Enable with ``PITWALL_LLM_MODE=byo`` and set PITWALL_LLM_PROVIDER / _MODEL
(and the provider key where required).
"""

from __future__ import annotations

import os


def llm_mode() -> str:
    """Return the active mode: 'byo' or 'free' (default)."""
    raw = os.getenv("PITWALL_LLM_MODE", "free").strip().lower()
    return "byo" if raw in {"byo", "bring-your-own", "llm", "on"} else "free"


def byo_llm_enabled() -> bool:
    """True when the bring-your-own LLM insight layer should run."""
    return llm_mode() == "byo"


def active_llm_label() -> str:
    """Human-readable description of the active LLM config for banners/logs."""
    if not byo_llm_enabled():
        return "free — rules only (no LLM)"
    provider = os.getenv("PITWALL_LLM_PROVIDER", "ollama").strip().lower() or "ollama"
    model = os.getenv("PITWALL_LLM_MODEL", "").strip()
    suffix = f" {model}" if model else ""
    return f"BYO — {provider}{suffix}"
