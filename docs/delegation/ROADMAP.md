# PitWallAI roadmap

**Product thesis:** in a friends' league, people use a fantasy bot that saves them from mistakes, knows
their league, and gives them something to argue about. Not one that out-models F1 Fantasy Tools.
**North-star metric:** league-mates who use the bot at least once per race weekend (a command *or* a button click).
**Sanity check:** the bot's picks vs the "three most expensive drivers" baseline. The eval harness that measured
this (`intelligence/eval/`) was deleted in brief 011, so it needs rebuilding before "Prove the picks" below.

## Timing
Remaining 2026 races (all standard weekends, no sprints; session times in UTC are in `core/calendar.py` after brief 012):
São Paulo Nov 6–8 · Las Vegas Nov 19–21 (local) · Qatar Nov 27–29 · Abu Dhabi Dec 4–6.

| When | Goal |
|---|---|
| **São Paulo** (Nov 6–8) | Dogfood. Brief 012 merged: picks keep working through the live-session lockout |
| **Las Vegas** (Nov 19–21) | Invite the league. Briefs 013–014 merged, the bot deployed on Railway |
| **Qatar + Abu Dhabi** | Trial the lock reminder and head-to-head (brief 015) with the league. Learning, not polish |
| **Off-season** | The rest of the social layer and a 2027 calendar. Launch properly before 2027 team selection |

## Done: foundation (briefs 000–011, merged)
CI green, behaviour snapshot, `core/` extracted, SQLite store, Slack `/pitwall` with
team/picks/grade/lock/score/record/forget/help, prices refresh automatically, legacy code deleted (~25k → ~5.5k lines).

## Now: data you can rely on during a race weekend
| # | Outcome | Fixes issue |
|---|---|---|
| 012 | Real session times; picks keep working through OpenF1's live-session lockout | 1 (lockout), 4 (misleading "no practice pace") |

**Why this comes before the social layer:** every scheduled post (lock reminder, ownership reveal, previews,
results) runs on race weekends, which is exactly when the free OpenF1 tier is locked. The posts also need correct
session times, and `core/calendar.py` currently uses one generic timetable for every race (it had Las Vegas
qualifying on the wrong day). 012 fixes the calendar, adds the "is data paused right now, and until when?" logic, and
adds the small in-process scheduler the social posts reuse. So it's both the top-priority bug fix and the first half
of the social foundation.

### Other known issues (not yet briefed)
| Issue | Where it goes |
|---|---|
| 2. `score` can't grade a past race without a locked lineup | "Any race" brief, after 015 |
| 3. picks/grade/lock only target the next race | Same "any race" brief |
| 5. "budget" is ambiguous (people enter the 100M cap) | Brief 014: the same-team "edit" path re-asks for money left, so fix the wording and add a sanity check there |
| 6. `slack_setup.md` step 4 says every reply is private; no "don't enable token rotation" warning | Brief 013 (it rewrites the setup doc for the new scopes anyway) |
| `.env.example` still describes the WhatsApp-era settings | Fold into any docs brief |

## Social layer
**Why:** with ~5 people, a season of individual fantasy scores goes quiet by mid-season. The bot runs a light side
game on top of the official one, so there's always a match this week and something to argue about.

### Principles
- **At most 3–4 bot posts in the channel per race week** (Mon–Sun, UTC). The cap is enforced in code (brief 013).
  Private DMs and replies to commands don't count.
- **Social forfeits only. Never money**, no betting framing (`DISCLAIMER.md`). Forfeits are things like "loser's
  Slack status is 🐌 for a week" or "picks the winner's walk-out song for the next race".
- **The bot is the 6th player** in a 5-person league. It locks its own lineup, so every game has an even count.
- **Our DB keeps the history.** The Slack free plan hides messages older than 90 days, so results, stints and the
  trophy cabinet live in SQLite and posts are regenerated from it.
- Same rules as the rest of the app: evidence-not-instructions wording, personal data private, `forget` erases it.

### Weekly rhythm
| Day | Post | Where |
|---|---|---|
| Monday | Awards for last race (best call, worst call, the bot's verdict) + head-to-head results | Channel |
| Thursday | Preview + prediction buttons (e.g. pole, winner, first DNF) | Channel |
| Saturday, before lock | "Same team as last week? ✅ / edit" lock reminder, with time left and unused transfers | DM to each player |
| Saturday, after lock | Ownership reveal: who owns whom, captains, differentials | Channel |
| Sunday | Race thread (results drop in after the race) | Channel |

That's four channel posts a week (Mon, Thu, Sat, Sun), which is the cap. The Saturday reminder is a DM.

### Mechanics
- **Weekly head-to-head:** 6 players → 3 matches each race. A round-robin of 6 takes 5 rounds, so it lines up with a stint.
- **Stints:** mini-seasons of 4–5 races, each with its own table and winner, so someone who's out of the season
  title race still has something to play for.
- **Trophy cabinet:** stint wins, weekly awards and head-to-head records, stored in our DB and viewable with a command.
- **Live watch-party thread** during the race (later). Needs OpenF1 Sponsor (~€10/month) for live data, so it's built
  only if more than half the league engages with the rest of the social layer (the "👋 I'm in" and prediction buttons give us the count).

### Build order
| # | Outcome | Depends on | Target |
|---|---|---|---|
| 012 | Real session times, data through the lockout, in-process scheduler | — | São Paulo |
| 013 | Social foundation: league channel, DMs, buttons, can't-post alert, weekly post cap | 012 | Las Vegas invite |
| 014 | Saturday lock reminder DM with "same team? ✅ / edit"; DM opt-out; clearer budget wording (issue 5); ownership reveal after lock (moves to 015 if 014 runs long) | 013 | Las Vegas lock (Fri 20 Nov, 23:00 ET) |
| 015 | Weekly head-to-head vs league-mates and the bot; Monday awards + results post | 014 | Qatar/Abu Dhabi trial |
| — | "Any race" fixes for score/picks/grade/lock (issues 2–3) | 015 | Off-season |
| 016 | Thursday preview + prediction buttons, scored on Monday | 015 | 2027 launch |
| 017 | Stints + trophy cabinet | 015 | 2027 launch |
| 018 | Live race thread (OpenF1 Sponsor) | 017, and the >50% engagement gate | 2027, maybe |

**Manual step before the league is invited:** deploy on Railway (`docs/slack_setup.md` §5). Scheduled posts and DMs
only fire while the process is running, so a sleeping laptop means missed reminders. Never run the local bot and
Railway with the same tokens at once: both would post. Set `PITWALL_SCHEDULER=off` locally (brief 012).

**Cost:** stays ~$5/month on Railway Hobby; the Slack free plan is fine (we store history ourselves). Only 018 adds cost.

### Before the 2027 season
- **2027 calendar** with real per-race session times, and sprint weekends locking at sprint qualifying (the 2026
  calendar never modelled that; no remaining 2026 race is a sprint, so it doesn't bite this year).
- Season rollover: stints, cabinet and head-to-head reset per season; the cabinet keeps past seasons.

## Next: other ideas (re-rank after the Qatar/Abu Dhabi trial)
Items "lock reminder", "the bot is a player" and "weekly channel posts" from the earlier list are now part of the social layer.
1. **Prove the picks:** rebuild a small eval over 2026 races vs the expensive-drivers baseline and post the result. If the bot loses, fix that before adding features.
2. **League-relative advice:** in `picks`, "You're 12 behind Sam; Sam owns NOR, you don't". Uses everyone's saved teams (shared only at league level, never another person's full team unprompted).
3. **Chips for the run-in:** "you still have Limitless and No Negative; here's where each fits in the races left".

## Later / maybe
- @-mention questions answered by an LLM calling `core.api` as tools.
- Screenshot team setup (only if typing teams turns out to be the friction).

## Not doing
Timestamped race "receipts", decode latency work, self-learning signal weights, public subscriber features, money stakes.
