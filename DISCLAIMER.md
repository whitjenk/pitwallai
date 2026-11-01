<!-- Update this file whenever user-facing features change the nature of recommendations made. -->

# Disclaimer

PitWallAI is an independent, open-source fan project created for entertainment purposes. It is not affiliated with, endorsed by, sponsored by, or connected to:

- Formula 1 / Formula One World Championship Ltd
- F1 Fantasy (the official game)
- ESPN or any ESPN affiliate
- Any F1 team, constructor, or driver
- The FIA (Fédération Internationale de l'Automobile)

## What PitWallAI is

A data analysis tool that processes publicly available race data (via OpenF1) and generates informational pick suggestions for use within the F1 Fantasy game. All outputs are observations and suggestions based on historical data and statistical models.

## What PitWallAI is not

- Official F1 Fantasy advice
- Financial, betting, or investment advice of any kind
- A guaranteed predictor of race outcomes or fantasy scores
- Affiliated with any paid fantasy gaming service

## Evidence-not-instruction policy

PitWallAI is designed to inform, not direct. All outputs use observational language ("practice data suggests", "historically strong at this circuit") rather than directive language ("transfer in", "use your chip now"). You make every decision. The system provides context.

## Data sources

Race data comes from [OpenF1](https://openf1.org/) (open-source, community maintained). Current player prices are read from the F1 Fantasy game's public price feed so budget maths stays accurate; they're used only inside the app and not redistributed. Prices and points in this repo are approximations of the published game rules. Always confirm transfers, budget and lock time in the official app.

## Accuracy

Picks are estimates from practice lap pace and qualifying, and they can be wrong. The bot scores its own picks against real results in the league channel, so you can see how it's doing. Past results don't guarantee future ones.

## Your data

PitWallAI runs inside a single Slack workspace. It stores your Slack user ID and display name, the team you save, and the lineups you lock, in one SQLite file controlled by whoever runs the bot. Nothing is sold or shared. Run `/pitwall forget` to erase everything it stores about you.

## Open source

PitWallAI is MIT licensed. The code, models, and methodology are fully open for inspection, contribution, and reuse. See [LICENSE](LICENSE) for terms.

---

Last updated: 2026-11-01
