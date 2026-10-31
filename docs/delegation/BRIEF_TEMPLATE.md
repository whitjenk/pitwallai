# Brief NNN: <outcome in one line — this is also the PR title>

**Status:** todo · **Size:** S / M (M = up to ~500 changed lines excl. deletions; bigger → split)
**Touches:** <main dirs/files>
**Depends on:** <brief numbers that must be merged first, or "nothing">
**Protected (must not be edited):** `tests/test_behaviour_snapshot.py`, `tests/snapshots/`, <others>

## Goal
One or two sentences: what will be true when this is done, and why it matters to a user or to you.

## Context
What the agent can't infer from the code: background, what you've already tried or verified,
the files to start from.

## In scope
- ...

## Out of scope
- ... (name the tempting adjacent work so the agent doesn't do it)

## Acceptance criteria
- [ ] <checkable statement> — verified by <test / command / manual step>
- [ ] Protected files untouched (`git diff --stat main -- <files>` is empty)
- [ ] Full test suite + `tools/language_linter.py` pass; CI green

## How I'll review it
What you'll actually do, in under 15 minutes, to decide merge or send back.
