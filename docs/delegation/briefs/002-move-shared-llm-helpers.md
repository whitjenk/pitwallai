# Brief 002: Move shared LLM and settings code out of the radio package

**Status:** todo · **Size:** S · **Touches:** new `pitwallai/llm/`, import lines across `intelligence/`, `whatsapp/`, `agents/`, `main.py`
**Depends on:** 001 merged.
**Protected:** `tests/test_behaviour_snapshot.py`, `tests/snapshots/`

## Goal
Pure move, no behaviour change. Afterwards, nothing outside `pitwallai/agents/radio_intercept/`
depends on that package for settings or LLM access, so brief 003 can delete it cleanly.

## Context
Three pieces of general-purpose code live inside the radio package:
- `radio_intercept/model_factory.py` (`get_model`, `resolve_api_key`): used by `intelligence/llm_insight.py`,
  `team_extractor.py`, `standings_extractor.py`, `constructor_strategy.py`
- `radio_intercept/config.py` (`PitWallSettings`, `DecodeBackend`): used by `main.py`,
  `whatsapp/`, `intelligence/`, `agents/quali_strategist.py`
- `radio_intercept/decoder_factory._sanitise_evidence_summary`: used by `intelligence/constructor_strategy.py`

## In scope
- Move them to `pitwallai/llm/model_factory.py`, `pitwallai/llm/settings.py`, `pitwallai/llm/sanitize.py`
  (make the sanitiser public: `sanitise_evidence_summary`).
- Update every import outside the radio package to the new paths.
- Inside the radio package, import from the new location. Don't leave copies.

## Out of scope
- Deleting anything. Renaming settings fields. Changing behaviour.

## Acceptance criteria
- [ ] `grep -rn "radio_intercept" --include=*.py . | grep -v "^./pitwallai/agents/radio_intercept\|^./tests"`
      only shows imports of genuinely radio things (agent, decoder, vector store), not model_factory/config/decoder_factory. List them in the PR
- [ ] Snapshot test passes unedited. Full suite passes. CI green
- [ ] The PR is moves plus import changes only. Point out any line that isn't

## How I'll review it
Skim the diff for anything that isn't an import change or a file move.
