"""Pydantic AI Radio Intercept Decoder agent."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import UTC, datetime

from loguru import logger
from pydantic import ValidationError
from pydantic_ai import Agent, RunContext

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


class DecodeValidationError(Exception):
    """Raised when the agent returns output that fails Pydantic validation."""


class DecodeRuntimeError(Exception):
    """Raised when the agent encounters a non-validation runtime failure."""


def build_system_prompt(deps: AgentDependencies) -> str:
    """
    Build the multi-paragraph system prompt for the Radio Intercept Decoder.

    Args:
        deps: Runtime agent dependencies including glossary and session context.

    Returns:
        Complete system prompt string.
    """
    glossary_lines = "\n".join(
        f"  - {term}: {meaning}" for term, meaning in sorted(deps.jargon_glossary.items())
    )
    return f"""You are the Radio Intercept Decoder on an F1 pit wall intelligence team. Your role is to \
decode live team radio transcriptions into structured tactical intelligence for the Lead Strategist \
Orchestrator. You operate under race pressure: be precise, evidence-driven, and conservative when uncertain.

MANDATORY TOOL USAGE:
1. ALWAYS call `query_historical_context` with the raw transcript BEFORE assigning `decoded_intent` or \
`strategic_signal`. Ground every classification in semantically similar historical precedents.
2. ALWAYS call `lookup_jargon` for any F1 radio jargon terms you recognize in the transcript (e.g. box, \
multi 21, delta, deploy, harvest, DRS, VSC, SC).
3. Call `get_driver_context` when the driver's communication style could disambiguate intent.

Active session key: {deps.session_key}
Maximum historical context results: {deps.max_context_results}

JARGON GLOSSARY (reference — also available via lookup_jargon tool):
{glossary_lines}

OUTPUT CONTRACT:
Your response will be parsed as a `DecodedTransmission`. Every field is required unless explicitly \
typed `| None`. Copy identity fields (session_key, driver_number, driver_code, team, timestamp, \
raw_transcript) exactly from the input message. Populate `jargon_decoded` with JargonEntry objects for \
each jargon term you identified. Set `context_doc_ids` to the doc_id values from historical results you \
used. Write `model_reasoning` as 2–4 sentences summarizing: what you heard, what historical precedents \
you found, what you concluded, and why.

HALLUCINATION GUARDRAILS:
- If confidence is below 0.4, set `decoded_intent` to `UNKNOWN` and `strategic_signal` to `UNKNOWN`.
- Never invent competitor intel. Only populate `competitor_intel` when the transcript explicitly \
references a rival driver or team with actionable evidence.
- Populate `evidence_summary` as a factual observation connecting what you heard to historical precedent \
and current context. This field is read by a human strategist as evidence — never phrase it as an \
instruction. Correct: 'Transcript matches 3 of 4 pre-box indicators observed at Bahrain 2023 lap 31. \
Gap to leader is 2.1s and closing.' Incorrect: 'Tell Lando to box now.' If there is no meaningful \
observation to make, set this field to None.
- Set `lap_number` when the transcript or input message references a lap.
- For event 6-style competitor observations (rival pit crew active, rival boxing), populate \
`competitor_intel` with `confirmation_state` UNCONFIRMED when evidence is explicit.
- Do not set `decoded_at`, `processing_latency_ms`, `team_color`, `exceeds_latency_target`, or \
`transmission_id` — these are injected post-decode."""


def _create_agent(model_name: str) -> Agent[AgentDependencies, DecodedTransmission]:
    """
    Instantiate the Pydantic AI agent with tools and structured output.

    Args:
        model_name: Anthropic model identifier.

    Returns:
        Configured Agent instance.
    """
    model_id = f"anthropic:{model_name}"
    try:
        agent = Agent(
            model_id,
            deps_type=AgentDependencies,
            result_type=DecodedTransmission,
        )
    except TypeError:
        agent = Agent(
            model_id,
            deps_type=AgentDependencies,
            output_type=DecodedTransmission,
        )

    @agent.system_prompt
    def dynamic_system_prompt(ctx: RunContext[AgentDependencies]) -> str:
        return build_system_prompt(ctx.deps)

    agent.tool(query_historical_context)
    agent.tool(lookup_jargon)
    agent.tool(get_driver_context)
    agent.tool(get_team_color)
    return agent


class RadioInterceptAgent:
    """
    Pydantic AI agent wrapper for decoding F1 team radio transmissions.

    Encapsulates model configuration, tool registration, and structured output validation.
    """

    def __init__(self, model_name: str = "claude-3-5-sonnet-20241022") -> None:
        """
        Initialize the Radio Intercept Decoder agent.

        Args:
            model_name: Anthropic Claude model identifier.
        """
        self._model_name = model_name
        self._agent = _create_agent(model_name)

    async def decode(
        self,
        message: RadioRawMessage,
        deps: AgentDependencies,
    ) -> DecodedTransmission:
        """
        Decode a raw radio message into structured tactical intelligence.

        Args:
            message: Validated raw radio ingestion payload.
            deps: Runtime dependencies including vector store and glossary.

        Returns:
            Fully validated DecodedTransmission with processing metadata injected.

        Raises:
            DecodeValidationError: If structured output fails Pydantic validation.
            DecodeRuntimeError: If the agent run fails for any other reason.
        """
        start_time = time.perf_counter()
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
            indent=2,
        )

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

        except ValidationError as exc:
            logger.bind(
                driver=message.driver_code,
                session=message.session_key,
            ).error("Decode validation failed: {}", exc)
            raise DecodeValidationError(str(exc)) from exc
        except (DecodeValidationError, DecodeRuntimeError):
            raise
        except Exception as exc:
            logger.bind(
                driver=message.driver_code,
                session=message.session_key,
            ).error("Decode runtime error: {}", exc)
            raise DecodeRuntimeError(str(exc)) from exc

        processing_latency_ms = (time.perf_counter() - start_time) * 1000
        team_color = deps.team_colors.get(message.team, "#FFFFFF")
        lap_number = output.lap_number if output.lap_number is not None else message.lap_number
        decoded = output.model_copy(
            update={
                "transmission_id": str(uuid.uuid4()),
                "decoded_at": datetime.now(tz=UTC),
                "processing_latency_ms": processing_latency_ms,
                "team_color": team_color,
                "exceeds_latency_target": processing_latency_ms > 800.0,
                "lap_number": lap_number,
            }
        )
        if decoded.decoded_at is None or decoded.processing_latency_ms is None:
            raise DecodeValidationError("Missing decoded_at or processing_latency_ms after injection")
        return decoded