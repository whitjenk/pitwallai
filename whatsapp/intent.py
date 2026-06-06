"""Natural-language intent resolution for inbound WhatsApp text.

Maps free-form messages ("should I play a chip?", "who do I pick", "how am I
doing?") to a canonical command token so users never need exact syntax. The
experience should feel like texting a knowledgeable friend, not a CLI.

Rules-first (offline, deterministic, zero-cost) with an optional Gemini fallback
when an LLM is configured. ``resolve_intent`` returns ``None`` when nothing
matches confidently, so mid-onboarding data entry (budgets, driver lists,
timezones) and exact commands pass through untouched.
"""

from __future__ import annotations

import os
import re

from loguru import logger

# Canonical commands the resolver may emit (base token before any argument).
_CANONICAL_COMMANDS = frozenset(
    {
        "PICKS", "TEAM", "HISTORY", "STREAK", "HELP", "CHIPS", "BUDGET",
        "TRANSFERS", "SEASON", "SETTINGS", "SUBSCRIBE", "UNSUBSCRIBE", "DELETE",
        "LIVE ON", "LIVE OFF", "CADENCE FULL", "CADENCE RACEDAY",
    }
)

# Chip free-text → canonical chip argument (for `CHIPS <name>` detail).
_CHIP_ALIASES: dict[str, str] = {
    "wildcard": "wildcard",
    "limitless": "limitless",
    "no negative": "no_negative",
    "no_negative": "no_negative",
    "autopilot": "autopilot",
    "auto pilot": "autopilot",
    "final fix": "final_fix",
    "final_fix": "final_fix",
    "extra drs": "extra_drs",
    "2x": "extra_drs",
    "double": "extra_drs",
}


def _driver_lookup() -> dict[str, str]:
    """Build {name-or-surname-or-code: CODE} from the driver label map."""
    from whatsapp.message_format import _DRIVER_LABELS

    out: dict[str, str] = {}
    for code, full in _DRIVER_LABELS.items():
        out[code.lower()] = code
        parts = full.lower().split()
        if parts:
            out[parts[-1]] = code  # surname
            out[parts[0]] = code  # first name
        out[full.lower()] = code
    return out


def _contains(t: str, *needles: str) -> bool:
    return any(n in t for n in needles)


# Commands that carry structured arguments — let the exact handler parse them
# rather than risk the natural-language layer grabbing a token (e.g. the driver
# code in "UPDATE D4 ALB" or "SHARE NOR").
_STRUCTURED_PREFIXES = frozenset({"update", "price", "share", "timezone", "cadence", "league"})


def resolve_intent(raw_text: str) -> str | None:
    """Map free text to a canonical command, or None when unsure.

    Pure rules — no network. Checks are ordered most-specific first.
    """
    stripped = raw_text.lower().strip()
    if not stripped:
        return None
    if stripped.split()[0] in _STRUCTURED_PREFIXES:
        return None

    t = f" {stripped} "

    # --- Grade a stated lineup ("I chose HAM, LEC, ANT, RUS, VER and MER, FER
    #     with limitless") → hand the whole message to the GRADE handler so it
    #     can score the picks. Must precede the chip block (a stated chip + a
    #     lineup is a grade request, not a chip-detail lookup).
    from fantasy.rules import DRIVER_PRICES_M

    codes_in_text = {
        tok for tok in re.findall(r"[A-Z]{2,3}", raw_text.upper()) if tok in DRIVER_PRICES_M
    }
    grade_signal = _contains(
        t, "i chose", "i picked", "i'm playing", "i am playing", "im playing",
        "i'm running", "im running", "i selected", "i went with", "my team is",
        "my lineup is", "grade my", "rate my", "what do you think", "how's my team",
        "hows my team", "i'm going with", "im going with", "i'm going to play",
    )
    chip_word = _contains(
        t, "limitless", "wildcard", "autopilot", "final fix", "no negative", "extra drs"
    )
    if len(codes_in_text) >= 3 and (grade_signal or chip_word):
        return f"GRADE {raw_text}"

    # --- Chips (highest priority — strong, unambiguous keywords) ---
    if _contains(t, "chip", "wildcard", "limitless", "autopilot", "final fix",
                 "no negative", "extra drs", "power up", "powerup", "power-up"):
        for alias, canon in _CHIP_ALIASES.items():
            if alias in t:
                return f"CHIPS {canon.upper()}"
        return "CHIPS"

    # --- Live race alerts on/off ---
    if _contains(t, "alert", "notif", "live") or "during the race" in t:
        if _contains(t, "off", "stop", "mute", "disable", "no more", "turn off", "silence"):
            return "LIVE OFF"
        if _contains(t, "on", "enable", "turn on", "start", "yes", "want", "notify"):
            return "LIVE ON"

    # --- Cadence ---
    if _contains(t, "race day only", "raceday", "only on race", "fewer message",
                 "less message", "too many message"):
        return "CADENCE RACEDAY"
    if _contains(t, "all the updates", "full updates", "everything", "every message"):
        return "CADENCE FULL"

    # --- Account lifecycle ---
    if _contains(t, "delete my data", "erase", "forget me", "wipe my", "gdpr", "remove my data"):
        return "DELETE"
    if _contains(t, "unsubscribe", "opt out", "stop messag", "stop texting", "leave",
                 "remove me"):
        return "UNSUBSCRIBE"
    if _contains(t, "subscribe", "sign me up", "sign up", "get started", "join"):
        return "SUBSCRIBE"

    # --- Season / standings ---
    if _contains(t, "season recap", "my season", "season so far", "how's my season",
                 "whole season"):
        return "SEASON"

    # --- Budget vs transfers ---
    if _contains(t, "budget", "how much money", "team value", "spare cash", "how much cash",
                 "money left", "in the bank"):
        return "BUDGET"
    transfer_count = _contains(t, "how many transfer", "transfers left", "transfers banked",
                               "free transfer", "transfers available", "transfers do i")
    if transfer_count:
        return "TRANSFERS"

    # --- Picks (catch the common "who/what should I…" asks) ---
    if _contains(t, "pick", "recommend", "who should i", "who do i", "lineup", "line up",
                 "captain", "best driver", "best pick", "suggestion", "what should i do",
                 "who to", "transfer in", "bring in", "good buy"):
        return "PICKS"
    if " transfer" in t:  # generic "transfers?" after the pick-specific phrases
        return "TRANSFERS"

    # --- Personal history vs system hit rate ---
    if _contains(t, "how am i doing", "my record", "my result", "past race", "how did i do",
                 "last race", "my history", "my score"):
        return "HISTORY"
    if _contains(t, "hit rate", "accuracy", "how accurate", "streak", "track record",
                 "how good are you", "win rate", "how often are you right", "are you any good"):
        return "STREAK"

    # --- Team setup ---
    if _contains(t, "my team", "set up team", "set up my team", "enter my team", "my squad",
                 "change my team", "update my team", "my lineup setup"):
        return "TEAM"

    # --- Driver question → card (or WHY when they ask "why/price") ---
    drivers = _driver_lookup()
    words = re.findall(r"[a-z]+", t)
    matched_codes = [drivers[w] for w in words if w in drivers]
    # A comma-separated list of several codes is a team entry, not a question.
    if "," in raw_text and len(set(matched_codes)) >= 3:
        return None
    if matched_codes:
        code = matched_codes[0]
        if _contains(t, "why", "price", "cheap", "expensive", "worth", "explain"):
            return f"WHY {code}"
        return code

    # --- Greetings / generic help (fallback) ---
    if _contains(t, "what can you do", "how does this work", "what do you do", "commands",
                 "menu", "options", "help") or t.strip() in {
        "hi", "hello", "hey", "yo", "sup", "start", "?",
    }:
        return "HELP"

    return None


def _llm_enabled_with_key() -> bool:
    """True only when an LLM that can actually authenticate is configured."""
    if os.getenv("PITWALL_NL_INTENT_LLM", "1").strip().lower() in {"0", "false", "no", "off"}:
        return False
    try:
        from pitwallai.agents.radio_intercept.config import PitWallSettings

        settings = PitWallSettings.from_env()
    except Exception:
        return False
    if settings.llm_api_key():  # BYOK / free Google AI Studio key
        return True
    # Vertex ADC path needs a project.
    return bool(settings.llm_use_vertex and settings.vertex_project)


_LLM_SYSTEM_PROMPT = (
    "You route an F1 fantasy WhatsApp user's message to exactly one command. "
    "Reply with ONLY one of these tokens, nothing else:\n"
    "PICKS, TEAM, HISTORY, STREAK, HELP, CHIPS, BUDGET, TRANSFERS, SEASON, "
    "SETTINGS, SUBSCRIBE, UNSUBSCRIBE, DELETE, LIVE_ON, LIVE_OFF, "
    "CADENCE_FULL, CADENCE_RACEDAY, NONE.\n"
    "Use CHIPS for any chip strategy question (wildcard, limitless, etc.). "
    "Use PICKS for who-to-pick/transfer-in questions. Reply NONE if unclear."
)


async def _llm_classify(raw_text: str) -> str | None:
    """Optional Gemini-backed classifier; returns a canonical token or None."""
    if not _llm_enabled_with_key():
        return None
    try:
        from pydantic_ai import Agent

        from pitwallai.agents.radio_intercept.config import PitWallSettings
        from pitwallai.agents.radio_intercept.model_factory import get_model

        settings = PitWallSettings.from_env()
        model = get_model(
            settings.llm_provider,
            settings.llm_api_key(),
            model_name=settings.llm_model,
            use_vertex=settings.llm_use_vertex,
            vertex_project=settings.vertex_project or None,
            vertex_location=settings.vertex_location or None,
        )
        agent = Agent(model, system_prompt=_LLM_SYSTEM_PROMPT, output_type=str)
        result = await agent.run(raw_text)
        token = (result.output or "").strip().upper().replace("_", " ")
        if token == "NONE":
            return None
        return token if token in _CANONICAL_COMMANDS else None
    except Exception as exc:  # never block inbound on the LLM
        logger.debug("nl_intent_llm_failed: {}", exc)
        return None


async def resolve_intent_smart(raw_text: str) -> str | None:
    """Rules first; fall back to the LLM classifier only when rules are unsure."""
    rule = resolve_intent(raw_text)
    if rule is not None:
        return rule
    return await _llm_classify(raw_text)
