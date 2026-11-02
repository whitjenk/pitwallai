# The delegation loop

You decide **what** and judge **whether it's right**. Agents do the **how**.
Each turn of the loop is one small, checkable change.

```
 1. PICK      next brief from ROADMAP.md whose dependencies are merged
 2. BRIEF     filled-in BRIEF_TEMPLATE.md; acceptance criteria you can check without reading code
 3. DELEGATE  fresh Claude Code session, kickoff prompt below; agent opens a PR
 4. VERIFY    CI green + a second, fresh "reviewer" session checks the PR against the brief
 5. REVIEW    you: run the brief's "How I'll review it" steps (time-boxed)
 6. MERGE or  merge — or send ONE round of specific feedback;
    REDIRECT  a second round means the brief was the problem: rewrite it, start a new session
 7. DOGFOOD   after anything user-facing ships, use it for a race weekend before writing the next feature brief
 8. LEARN     anything you explained twice → CLAUDE.md (keep it short; detail belongs in briefs)
```

## Kickoff prompt (step 3)
Paste into a new Claude Code session on the repo:

> Read `CLAUDE.md`, then do `docs/delegation/briefs/NNN-<slug>.md`. Work on branch
> `agent/NNN-<slug>` from latest `main`. Don't edit protected files listed in the brief. When every acceptance
> criterion is met, open a PR titled with the brief's outcome line, with each criterion ticked and the evidence
> next to it. If something in the brief is wrong or impossible, stop and tell me instead of working around it.

## Reviewer prompt (step 4)
Paste into a *different* new session after the PR is open:

> You are reviewing PR #N against `docs/delegation/briefs/NNN-<slug>.md`. Don't fix anything.
> For each acceptance criterion: met / not met / can't tell, with evidence (command output, file + line).
> Then list: edits to protected files, changes outside the brief's scope, and anything that would
> surprise the person who wrote the brief. End with "merge" or "send back" and why.

## Rules
- **CI must be green on `main`.** If it goes red, fixing it is the next brief, ahead of everything else.
- **Behaviour snapshot is sacred.** `tests/snapshots/` changes only when a brief explicitly says so.
  Any other diff there is an automatic send-back.
- **PR size cap: ~500 changed lines, not counting pure deletions and file moves.** Bigger means the brief gets split.
- **Parallel only when briefs don't touch the same files.** The "Depends on" line in each brief is the source of truth.
- **One review round.** If your feedback needs a second round, the brief was unclear. Fix the brief, not the PR.
- **Name PRs after the outcome**, e.g. "Get CI green without deleting anything", never "whitj-pitwallai-9".

## Tracking
One GitHub issue per brief, titled with its outcome line, linking to the brief file. The issue is the status
(open → PR linked → closed). The brief file holds the content. Don't track status in two places.

## Parallel lanes for the current plan
```
000 ─┬─ 001 ── 002 ── 003 ── 004 ─┬─ 006 ── 007 ── 008 ── 009 ── 010 ── 011
     └────────── 005 ─────────────┘
```
005 can run alongside any of 001–004.

Social layer (ROADMAP → Social layer) is strictly sequential, since every brief touches `slack_app/handlers.py` and `store/db.py`:
```
012 ── 013 ── 014 ── 015 ─┬─ "any race" fixes ── 016 ── 017 ── 018 (gated)
```
