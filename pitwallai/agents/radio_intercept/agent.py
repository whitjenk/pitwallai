"""Radio intercept decoder facade (rules-first, optional LLM)."""

from __future__ import annotations

from pitwallai.agents.radio_intercept.config import DecodeBackend, PitWallSettings
from pitwallai.agents.radio_intercept.decoder_factory import HybridDecoder, create_decoder
from pitwallai.agents.radio_intercept.errors import DecodeRuntimeError, DecodeValidationError
from pitwallai.agents.radio_intercept.models import AgentDependencies, DecodedTransmission, RadioRawMessage
from pitwallai.agents.radio_intercept.prompts import build_system_prompt

__all__ = [
    "DecodeRuntimeError",
    "DecodeValidationError",
    "RadioInterceptAgent",
    "build_system_prompt",
]


class RadioInterceptAgent:
    """
    Facade for transmission decoding.

    Default backend is **rules** (vector retrieval + patterns): no API keys, sub-100 ms.
    Set ``PITWALL_DECODE_BACKEND=hybrid`` and ``PITWALL_LLM_MODEL=openai:gpt-4o-mini`` to
    escalate only low-confidence cases to an LLM.
    """

    def __init__(
        self,
        backend: str | DecodeBackend | None = None,
        llm_model: str | None = None,
        settings: PitWallSettings | None = None,
    ) -> None:
        """
        Initialize the decoder facade.

        Args:
            backend: Override decode backend (rules, llm, hybrid).
            llm_model: Override Pydantic AI model id (provider:model).
            settings: Optional full settings object.
        """
        self._settings = settings or PitWallSettings.from_env()
        backend_str = backend.value if isinstance(backend, DecodeBackend) else backend
        self._decoder: HybridDecoder = create_decoder(
            settings=self._settings,
            backend=backend_str,
            llm_model=llm_model,
        )

    @property
    def settings(self) -> PitWallSettings:
        """Return active settings."""
        return self._settings

    async def decode(
        self,
        message: RadioRawMessage,
        deps: AgentDependencies,
    ) -> DecodedTransmission:
        """
        Decode a raw radio message.

        Args:
            message: Validated raw radio payload.
            deps: Shared dependencies.

        Returns:
            Structured decode result.
        """
        return await self._decoder.decode(message, deps)
