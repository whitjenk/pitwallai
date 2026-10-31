# Brief 007: Slack app, part 2: grade, lock, score, record

**Status:** todo · **Size:** M · **Touches:** `slack_app/`, `tests/test_slack_handlers.py`
**Depends on:** 006 merged.
**Protected:** `tests/test_behaviour_snapshot.py`, `tests/snapshots/`, `railway.toml`

## Goal
The banter commands. Grading a lineup and seeing scores and the season record post in the
channel, so the league can react. Locking is private, apart from a one-line "@user locked in".

## Context
- Logic: `core.api.grade_lineup`, `score_lineup`. Persistence: `store.lock_lineup`, `get_locked`, `list_locked_for_race`.
- Lineup parsing: `core/parse.py` from brief 006.
- Wording to adapt: `_handle_grade`, `_handle_lock`, `_handle_score`, `_handle_record` in `whatsapp/inbound.py`.

## In scope
| Command | Example | Visibility |
|---|---|---|
| `grade <lineup>` | `/pitwall grade HAM LEC ANT RUS VER MER FER captain HAM 3x` | channel |
| `lock <lineup>` | saves it plus the bot's own pick at lock time | ephemeral confirmation + one channel line "@user locked in for <race>" (no lineup shown) |
| `score [race]` | your locked lineup vs the bot vs the actual result vs the perfect lineup | channel |
| `record` | your season so far, and how often you beat the bot | channel |

- Add these to `help`.

## Out of scope
- Scheduled posts, leaderboards across users (roadmap), deploy.

## Acceptance criteria
- [ ] Tests cover: grade with chip and captain, `lock` twice replaces, the channel line from `lock` doesn't reveal the lineup,
      `score` with nothing locked gives a hint, `record` with zero races
- [ ] Visibility for each command matches the table (asserted in tests)
- [ ] No network in tests. CI green

## How I'll review it
In a test channel: lock, grade, then score a past race. Check who can see what.
