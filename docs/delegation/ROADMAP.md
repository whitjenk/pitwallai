# PitWallAI roadmap

**Product thesis:** in a friends' league, people use a fantasy bot that saves them from mistakes, knows
their league, and gives them something to argue about. Not one that out-models F1 Fantasy Tools.
**North-star metric:** league-mates who use the bot at least once per race weekend.
**Sanity check:** the bot's picks vs the "three most expensive drivers" baseline (`intelligence/eval/baselines.py`).

## Timing
Remaining 2026 races: São Paulo Nov 6–8 · Las Vegas Nov 19–21 · Qatar Nov 27–29 · Abu Dhabi Dec 4–6.
- **By Las Vegas:** briefs 000–006 merged; I'm using `/pitwall` myself.
- **Qatar + Abu Dhabi:** two-race beta with the league. Goal is learning what gets used, not polish.
- **Off-season:** build "Next" and launch properly before 2027 team selection, when engagement peaks.

## Now: foundation (briefs written)
| # | Outcome |
|---|---|
| 000 | CI green without deleting anything (+ DELETE privacy fix) |
| 001 | Snapshot test proving refactors don't change answers |
| 002 | Shared LLM/settings code moved out of the radio package |
| 003 | Radio intercept stack and heavy dependencies deleted |
| 004 | Fantasy brain extracted to `core/` |
| 005 | SQLite store keyed by Slack user |
| 006 | Slack: team + picks (private) |
| 007 | Slack: grade, lock, score, record (channel) |
| 008 | Production switched to Slack (WhatsApp off, Railway Hobby) |
| 009 | Prices stay current automatically (bot was on January prices) |
| 010 | Bot proven to run with all legacy packages absent |
| 011 | Legacy code, database layer and public-product docs deleted (~25k → ~5k lines) |

## Next: what makes people use it (write briefs after dogfooding 006/007)
Ordered by expected value; re-rank after the beta.
1. **Prove the picks:** run the eval harness over 2026 races vs both baselines, post the result in the channel. If the bot loses to the expensive-drivers baseline, fix that before adding features.
2. **Lock reminder + team check:** a few hours before lock, DM each player: time left, unused free transfers, any driver replaced, and "still this team? ✅ / edit". This keeps saved teams in sync with the official app.
3. **The bot is a player:** PitWallAI locks its own lineup each week in the channel. Season standings "humans vs the bot".
4. **League-relative advice:** in `picks`, "You're 12 behind Sam; Sam owns NOR, you don't". Uses everyone's saved teams (only shared at league level, never another person's full team unprompted).
5. **Chips for the run-in:** "you still have Limitless and No Negative; here's where each fits in the races left".
6. **Weekly channel posts:** Friday "what changed after practice", Monday leaderboard and the bot's best/worst call.

## Later / maybe
- @-mention questions answered by an LLM calling `core.api` as tools.
- Screenshot team setup (only if typing teams turns out to be the friction).

## Not doing
Timestamped race "receipts", decode latency work, self-learning signal weights, public subscriber features.
