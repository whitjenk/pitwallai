"""Provider-agnostic Pydantic AI model factory."""

from __future__ import annotations

import os
from typing import Literal

from pydantic_ai.models import Model

ProviderName = Literal["gemini", "claude", "openai", "ollama"]

_DEFAULT_MODELS: dict[str, str] = {
    "gemini": "gemini-2.0-flash",
    "claude": "claude-3-5-sonnet-latest",
    "openai": "gpt-4o-mini",
    "ollama": "llama3.2",
}

_SUPPORTED_PROVIDERS = frozenset(_DEFAULT_MODELS)


def get_model(
    provider: str,
    api_key: str,
    *,
    model_name: str | None = None,
    vertex_project: str | None = None,
    vertex_location: str | None = None,
    use_vertex: bool = True,
    ollama_base_url: str = "http://localhost:11434/v1",
) -> Model:
    """
    Return a Pydantic AI model for the given provider.

    The decode prompt and output schema are identical for every provider; only the
    underlying model client differs.

    Args:
        provider: One of gemini, claude, openai, ollama.
        api_key: Provider API key (BYOK). Vertex AI uses Application Default
            Credentials when api_key is empty and use_vertex is True.
        model_name: Model id override; defaults per provider if omitted.
        vertex_project: Google Cloud project for Vertex AI.
        vertex_location: Google Cloud region for Vertex AI.
        use_vertex: When True and provider is gemini, use Vertex AI (google-vertex).
        ollama_base_url: OpenAI-compatible Ollama endpoint.

    Returns:
        Configured Pydantic AI Model instance.

    Raises:
        ValueError: If provider is unknown.
    """
    normalized = provider.strip().lower()
    if normalized not in _SUPPORTED_PROVIDERS:
        raise ValueError(
            f"Unsupported LLM provider '{provider}'. "
            f"Choose from: {', '.join(sorted(_SUPPORTED_PROVIDERS))}"
        )

    resolved_name = model_name or _DEFAULT_MODELS[normalized]

    if normalized == "gemini":
        from pydantic_ai.models.google import GoogleModel
        from pydantic_ai.providers.google import GoogleProvider

        if api_key.strip():
            google_provider = GoogleProvider(api_key=api_key.strip())
        elif use_vertex:
            google_provider = GoogleProvider(
                vertexai=True,
                project=vertex_project or os.getenv("GOOGLE_CLOUD_PROJECT"),
                location=vertex_location or os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
            )
        else:
            google_provider = GoogleProvider()
        return GoogleModel(resolved_name, provider=google_provider)

    if normalized == "claude":
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.providers.anthropic import AnthropicProvider

        return AnthropicModel(
            resolved_name,
            provider=AnthropicProvider(api_key=api_key.strip() or None),
        )

    if normalized == "openai":
        from pydantic_ai.models.openai import OpenAIModel
        from pydantic_ai.providers.openai import OpenAIProvider

        return OpenAIModel(
            resolved_name,
            provider=OpenAIProvider(api_key=api_key.strip() or None),
        )

    # ollama — OpenAI-compatible local server
    from pydantic_ai.models.openai import OpenAIModel
    from pydantic_ai.providers.openai import OpenAIProvider

    key = api_key.strip() or "ollama"
    return OpenAIModel(
        resolved_name,
        provider=OpenAIProvider(base_url=ollama_base_url, api_key=key),
    )


def resolve_api_key(provider: str) -> str:
    """
    Resolve BYOK API key from environment for a provider.

    Args:
        provider: Provider name (gemini, claude, openai, ollama).

    Returns:
        API key string (may be empty for Vertex ADC or Ollama).
    """
    normalized = provider.strip().lower()
    env_map = {
        "gemini": ("PITWALL_GOOGLE_API_KEY", "GOOGLE_API_KEY"),
        "claude": ("PITWALL_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
        "openai": ("PITWALL_OPENAI_API_KEY", "OPENAI_API_KEY"),
        "ollama": ("PITWALL_OLLAMA_API_KEY",),
    }
    for var in env_map.get(normalized, ()):
        value = os.getenv(var, "").strip()
        if value:
            return value
    return ""
