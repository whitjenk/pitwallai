# Brief 002: README points at this repo, not the old one

**Status:** todo · **Size:** S · **Touches:** `README.md`, `BETA_INVITE.md`

## Goal
Someone landing on github.com/whitjenk/pitwallai can copy the "Run it yourself" commands and
they work, and the CI badge shows this repo's real status.

## Context
`README.md` still refers to the old repo name `whitjenk/f1-tactical-intelligence-hive` in the
CI badge URL, the `git clone` command, and the `cd` line. The "Season GP pick hit rate"
section has a placeholder `[Link to live leaderboard]`.
`BETA_INVITE.md` line 79 sends beta users to a PRIVACY.md link on the old repo — that one matters most.

## In scope
- Replace every `f1-tactical-intelligence-hive` reference in `README.md` and `BETA_INVITE.md`
  with `pitwallai` (badge, clone URL, directory name).
- Change the README's venv instructions to say Python 3.11 is required.

## Out of scope
- Rewriting product copy or restructuring the README.
- The leaderboard placeholder — leave it, but list it under Follow-ups.

## Acceptance criteria
- [ ] `grep -rn "f1-tactical-intelligence-hive" --include=*.md --exclude-dir=delegation .` returns nothing
- [ ] Badge URL is `https://github.com/whitjenk/pitwallai/actions/workflows/ci.yml/badge.svg`
- [ ] `tools/language_linter.py` passes

## How I'll review it
Open the rendered README on the PR branch; click the badge.
