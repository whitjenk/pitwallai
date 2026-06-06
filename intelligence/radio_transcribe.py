"""Local speech-to-text for OpenF1 team-radio audio.

OpenF1's /team_radio endpoint exposes an audio ``recording_url`` (.mp3) but no
text transcript, so the radio-sentiment pipeline has nothing to decode on real
data. This module fills that gap by transcribing those clips locally with
faster-whisper — free, no API key, no billed model (honours the repo's
free-models-only guardrail). It is opt-in and lazily imported: nothing here
loads faster-whisper (or downloads a model) unless transcription is actually
requested.

Enable in the practice pipeline with ``PITWALL_RADIO_TRANSCRIBE=true``. Pick a
model with ``PITWALL_WHISPER_MODEL`` (tiny.en | base.en | small.en …; default
base.en — a good speed/accuracy balance on CPU).
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import httpx
from loguru import logger

_DEFAULT_MODEL = "base.en"
_model = None  # cached WhisperModel singleton


def transcription_enabled() -> bool:
    """True when the pipeline should transcribe team-radio audio."""
    return os.getenv("PITWALL_RADIO_TRANSCRIBE", "").strip().lower() in {"1", "true", "yes"}


def _get_model():
    """Lazily construct and cache the faster-whisper model (CPU, int8)."""
    global _model
    if _model is None:
        from faster_whisper import WhisperModel  # imported lazily on first use

        size = os.getenv("PITWALL_WHISPER_MODEL", _DEFAULT_MODEL)
        logger.info("Loading faster-whisper model={} (cpu/int8)", size)
        _model = WhisperModel(size, device="cpu", compute_type="int8")
    return _model


def _transcribe_file(path: str) -> str:
    """Blocking transcription of a local audio file → joined transcript text."""
    model = _get_model()
    segments, _info = model.transcribe(path, language="en", vad_filter=True)
    return " ".join(seg.text.strip() for seg in segments).strip()


async def transcribe_url(url: str, *, timeout_s: float = 30.0) -> str:
    """
    Download one team-radio clip and transcribe it locally.

    Returns the transcript text, or "" on any download/decode failure (the
    caller should degrade gracefully — a missing transcript just means no
    radio signal for that clip).
    """
    tmp_path: str | None = None
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            audio = resp.content
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp.write(audio)
            tmp_path = tmp.name
        return await asyncio.to_thread(_transcribe_file, tmp_path)
    except Exception as exc:  # noqa: BLE001 — transcription is best-effort
        logger.warning("Radio transcription failed url={}: {}", url, exc)
        return ""
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)


async def transcribe_entries(entries: list, *, max_concurrency: int = 2) -> list:
    """
    Populate ``.transcript`` on team-radio entries that have audio but no text.

    Args:
        entries: TeamRadioEntry models (have ``recording_url`` / ``transcript``).
        max_concurrency: Parallel transcriptions (CPU-bound; keep small).

    Returns:
        New entry list with transcripts filled where possible. Entries that
        already carry a transcript, or lack a recording_url, pass through.
    """
    sem = asyncio.Semaphore(max_concurrency)

    async def _one(entry):
        if entry.raw_transcript or not entry.recording_url:
            return entry
        async with sem:
            text = await transcribe_url(entry.recording_url)
        return entry.model_copy(update={"transcript": text}) if text else entry

    todo = sum(1 for e in entries if not e.raw_transcript and e.recording_url)
    if todo:
        logger.info("Transcribing {} team-radio clip(s) locally", todo)
    return await asyncio.gather(*(_one(e) for e in entries))
