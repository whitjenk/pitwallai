# The delegation loop

You decide **what** and judge **whether it's right**. Agents do the **how**.
Each turn of the loop is one small, checkable change.

```
 1. PICK      choose one outcome from the backlog (small: ~1 PR, < 1 day of human work)
 2. BRIEF     write it up with BRIEF_TEMPLATE.md — goal, context, scope, acceptance criteria
 3. DELEGATE  hand the brief to an agent (Claude Code session / GitHub issue → PR)
 4. VERIFY    CI green + agent's own checklist; you don't read code yet
 5. REVIEW    read the PR against the acceptance criteria, then try it yourself
 6. MERGE or  merge it — or send back ONE round of specific feedback;
    REDIRECT  if a second round is needed, the brief was the problem: rewrite it
 7. LEARN     anything you had to explain twice goes into CLAUDE.md
```

## Rules of thumb
- **The brief is the product.** Most bad agent output comes from a vague brief. Spend your
  time on acceptance criteria — they tell the agent when it's finished and tell you what to check.
- **Criteria must be checkable.** "Picks feel better" is not a criterion. "`PICKS` reply
  names the constructor and its price; covered by a test in `test_command_router.py`" is.
- **Keep CI green.** A red main branch means you can't tell whether an agent broke something.
  Fixing CI is always brief #1.
- **Run tasks in parallel only when they don't touch the same files.** Two agents editing
  `whatsapp/command_router.py` at once means merge conflicts.
- **Name PRs after the outcome**, e.g. "Pin opentelemetry so fresh installs pass CI",
  not "whitj-pitwallai-9". Your history becomes a changelog.
- **Time-box your review.** If reviewing a PR takes longer than writing the brief did, the task was too big — split the next one.

## Where briefs live
`docs/delegation/briefs/NNN-slug.md`, or as GitHub issues using the same template.
Status goes at the top of each brief: `todo` → `delegated` → `in review` → `done`.
