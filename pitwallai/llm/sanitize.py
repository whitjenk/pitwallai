"""Strip directive language from LLM evidence summaries."""

from __future__ import annotations

import re

# Phrases that turn evidence into strategist directives (forbidden in evidence_summary).
_DIRECTIVE_PHRASES: tuple[str, ...] = (
    "box now",
    "pit now",
    "you should",
    "you must",
    "we should",
    "recommend",
    "recommended",
    "immediately",
    "need to box",
    "need to pit",
    "must box",
    "must pit",
    "consider boxing",
    "consider pitting",
    "deploy now",
    "push now",
)

_IMPERATIVE_SENTENCE = re.compile(
    r"^\s*(box|pit|push|deploy|recommend|consider|must|should)\b",
    re.IGNORECASE,
)


def sanitise_evidence_summary(text: str | None) -> str | None:
    """
    Strip directive language from LLM evidence summaries.

    The evidence_summary field must contain factual observations only — never
    instructions, recommendations, or action verbs directed at the strategist.

    Args:
        text: Raw LLM evidence summary.

    Returns:
        Sanitised summary, or None if nothing observational remains.
    """
    if text is None:
        return None
    cleaned = text.strip()
    if not cleaned:
        return None

    for phrase in _DIRECTIVE_PHRASES:
        cleaned = re.sub(re.escape(phrase), "", cleaned, flags=re.IGNORECASE)

    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,;.-")

    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    observational = [
        sentence.strip()
        for sentence in sentences
        if sentence.strip() and not _IMPERATIVE_SENTENCE.match(sentence.strip())
    ]
    result = " ".join(observational).strip()
    return result if result else None
