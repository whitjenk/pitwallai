"""Optional LLM-backed decoder (provider-agnostic via Pydantic AI)."""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING

from loguru import logger
from pydantic import ValidationError
from pydantic_ai import Agent, RunContext
from pydantic_ai.models import Model

from pitwallai.agents.radio_intercept.config import PitWallSettings
from pitwallai.agents.radio_intercept.errors import DecodeRuntimeError, DecodeValidationError
from pitwallai.agents.radio_intercept.llm_budget import LLMBudgetGuard
from pitwallai.agents.radio_intercept.model_factory import get_model
from pitwallai.agents.radio_intercept.prompts import build_system_prompt
from pitwallai.agents.radio_intercept.decode_utils import finalize_transmission
from pitwallai.agents.radio_intercept.models import (
    AgentDependencies,
    DecodedTransmission,
    RadioRawMessage,
)
from pitwallai.agents.radio_intercept.tools import (
    get_driver_context,
    get_team_color,
    lookup_jargon,
    query_historical_context,
)

if TYPE_CHECKING:
    pass


def _create_llm_agent(model: str | Model) -> Agent[AgentDependencies, DecodedTransmission]:
    """
    Instantiate a Pydantic AI agent for the configured model.

    Args:
        model: Pydantic AI Model instance or legacy provider:model string.

    Returns:
        Configured Agent with shared prompt and output schema.
    """
    try:
        agent = Agent(
            model,
            deps_type=AgentDependencies,
            output_type=DecodedTransmission,
        )
    except TypeError:
        agent = Agent(
            model,
            deps_type=AgentDependencies,
            result_type=DecodedTransmission,
        )

    @agent.system_prompt
    def dynamic_system_prompt(ctx: RunContext[AgentDependencies]) -> str:
        return build_system_prompt(ctx.deps)

    agent.tool(query_historical_context)
    agent.tool(lookup_jargon)
    agent.tool(get_driver_context)
    agent.tool(get_team_color)
    return agent


class LLMDecoder:
    """
    LLM decoder using Pydantic AI with any supported provider.

    Only invoked when explicitly configured; not used in default rules mode.
    """

    def __init__(
        self,
        settings: PitWallSettings,
        semaphore: asyncio.Semaphore | None = None,
        budget_guard: LLMBudgetGuard | None = None,
    ) -> None:
        """
        Initialize the LLM decoder.

        Args:
            settings: Application settings (provider, model, Vertex config).
            semaphore: Optional concurrency limiter for API calls.
            budget_guard: Optional budget guard (checked by HybridDecoder before calls).
        """
        self._settings = settings
        model = get_model(
            settings.llm_provider,
            settings.llm_api_key(),
            model_name=settings.llm_model,
            vertex_project=settings.vertex_project or None,
            vertex_location=settings.vertex_location,
            use_vertex=settings.llm_use_vertex,
            ollama_base_url=settings.ollama_base_url,
        )
        self._agent = _create_llm_agent(model)
        self._semaphore = semaphore
        self._budget_guard = budget_guard

    async def decode(
        self,
        message: RadioRawMessage,
        deps: AgentDependencies,
    ) -> DecodedTransmission:
        """
        Decode via LLM structured output.

        Args:
            message: Raw radio message.
            deps: Agent dependencies.

        Returns:
            Decoded transmission.

        Raises:
            DecodeValidationError: On schema validation failure.
            DecodeRuntimeError: On model/runtime errors.
        """
        started = time.perf_counter()
        user_message = json.dumps(
            {
                "session_key": message.session_key,
                "driver_number": message.driver_number,
                "driver_code": message.driver_code,
                "team": message.team,
                "timestamp": message.timestamp.isoformat(),
                "raw_transcript": message.raw_transcript,
                "recording_url": message.recording_url,
                "lap_number": message.lap_number,
            },
            separators=(",", ":"),
        )

        async def _run() -> DecodedTransmission:
            try:
                try:
                    run_result = await self._agent.run_async(user_message, deps=deps)
                except AttributeError:
                    run_method = self._agent.run
                    if asyncio.iscoroutinefunction(run_method):
                        run_result = await run_method(user_message, deps=deps)
                    else:
                        run_result = await asyncio.to_thread(
                            run_method,
                            user_message,
                            deps=deps,
                        )
                output = run_result.output
                if not isinstance(output, DecodedTransmission):
                    output = DecodedTransmission.model_validate(output)
                return finalize_transmission(output, message, deps, started)
            except ValidationError as exc:
                logger.bind(driver=message.driver_code).error("LLM validation failed: {}", exc)
                raise DecodeValidationError(str(exc)) from exc
            except (DecodeValidationError, DecodeRuntimeError):
                raise
            except Exception as exc:
                logger.bind(driver=message.driver_code).error("LLM runtime error: {}", exc)
                raise DecodeRuntimeError(str(exc)) from exc

        if self._semaphore is None:
            return await _run()
        async with self._semaphore:
            return await _run()
