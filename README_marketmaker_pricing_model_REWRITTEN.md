# NCAA Basketball Market Maker Predictive Pricing Model

## Overview

This project is a daily-updating college basketball pricing engine designed for **market making, derivative pricing, and trading support**. It combines:

- **KenPom predictive statistics**
- **raw team and player feed data**
- **live market odds**
- **team-by-team tempo and efficiency modeling**
- **joint score-distribution logic**
- **derived spread / total / moneyline pricing**

The objective is not to produce a black-box pick sheet. The objective is to build a **transparent, explainable, and tradeable basketball pricing framework** that can be updated daily from a local terminal workflow.

---

## Core Design Principle

This model does **not** rely on the naive assumption that team scoring outcomes are independent.

In basketball, home and away scoring are linked through:

- shared possessions
- shared tempo regime
- shared shot-variance environment
- foul environment
- endgame behavior
- overtime risk

Accordingly, the pricing engine is described as a **joint exact-score framework**, not a naive product of marginal score distributions.

---

## Mathematical Framework

Let:

- `X` = home team points
- `Y` = away team points
- `N` = shared game possessions / pace state
- `G` = shared game environment shock

Then the intended score-distribution framework is:

\[
P(X=x,Y=y)=\sum_n \sum_g P(N=n,G=g)\,P(X=x\mid N=n,G=g)\,P(Y=y\mid N=n,G=g)
\]

This means:

- team score outcomes are **not independent**
- both teams are linked through shared game state
- spread and total prices are derived from a **joint scoring surface**

From that score surface, the model derives:

- **moneyline probabilities**
- **spread cover probabilities**
- **total probabilities**
- **alternate spread ladders**
- **alternate total ladders**
- **team-total style logic (future extension)**

---

## Basketball-Specific Predictive Engine

### 1) Team Tempo Modeling

Each team has a blended tempo estimate built from:

- KenPom adjusted tempo
- raw team-feed pace
- recent pace / short-horizon pace

A representative team tempo blend is:

\[
TeamTempo = w_{KP}\cdot AdjT + w_{raw}\cdot RawTempo + w_{recent}\cdot RecentTempo
\]

with weights summing to 1.

A practical default:

- `w_KP = 0.60`
- `w_raw = 0.25`
- `w_recent = 0.15`

### 2) Shared Game Possessions

The game does **not** use separate possessions for each team. Both teams share one possession environment.

The model therefore estimates **Expected Game Possessions** as a blended interaction of both teams' tempo tendencies, using a harmonic-style blend and shrinkage toward league average:

\[
BaseTempo = \frac{2}{1/HomeTeamTempo + 1/AwayTeamTempo}
\]

\[
ExpectedTempo = 0.85\cdot BaseTempo + 0.15\cdot LeagueAvgTempo
\]

This gives a more stable game pace than a simple arithmetic average.

### 3) Team-Specific Offensive Efficiency

The model estimates each team's expected offensive rating using:

- team offensive strength
- opponent defensive strength
- home-court effect
- player / rotation adjustments
- optional manual overrides

Representative structure:

\[
ExpHomeORtg =
LeagueAvgOE
+ 0.55(HomeAdjOE - LeagueAvgOE)
+ 0.45(AwayAdjDE - LeagueAvgDE)
+ HCA
+ HomeAdj
- AwayDefenseAdj
\]

\[
ExpAwayORtg =
LeagueAvgOE
+ 0.55(AwayAdjOE - LeagueAvgOE)
+ 0.45(HomeAdjDE - LeagueAvgDE)
- HCA
+ AwayAdj
- HomeDefenseAdj
\]

**Important sign convention:** lower defensive efficiency is better defense, so the opponent defense term must be handled with the correct sign.

### 4) Expected Team Points

Once shared possessions and team-specific ORtg are estimated:

\[
ExpHomePts = ExpectedTempo \cdot ExpHomeORtg / 100
\]

\[
ExpAwayPts = ExpectedTempo \cdot ExpAwayORtg / 100
\]

### 5) Fair Margin and Fair Line

The model margin is:

\[
FairHomeMargin = ExpHomePts - ExpAwayPts
\]

The **Fair Home Line** is:

\[
FairHomeLine = -FairHomeMargin
\]

This keeps the betting convention consistent:

- positive Home Line = home team gets points
- negative Home Line = home team lays points

### 6) Derived Market Probabilities

From the scoring / margin / total framework, the workbook derives:

- `Home Win %`
- `Home Cover %`
- `Over %`
- `Fair ML`
- `Fair spread price`
- `Fair total price`

---

## PMF / Distribution Layer

The workbook includes visible full-curve distributions in `SpreadTotal` for:

- **home margin distribution**
- **game total distribution**
- **market-implied curve**
- **model-implied curve**

These curves are used to support:

- alternate spread pricing
- alternate total pricing
- fair odds ladders
- sanity-check visuals for the pricing surface

The visible workbook currently emphasizes the **derived margin and total distributions** used for pricing, while the broader modeling concept is framed around a joint score-distribution structure.

---

## Data Inputs

The model is designed to use:

### KenPom Inputs
- adjusted offensive efficiency
- adjusted defensive efficiency
- adjusted tempo
- projected tempo (when available)
- thrill score (when available)
- matchup-level sanity-check fields from FanMatch when available

### Raw Team / Player Inputs
- team-feed season metrics
- recent form / short-horizon metrics
- player availability / rotation state
- roster-impact adjustments
- optional manual overrides

### Market Inputs
- spread lines
- total lines
- multi-book odds snapshots
- selected / preferred market line source
- consensus fallback with tick snapping

---

## Workbook Structure

### Control Workbook (`.xlsm`)
Used for:
- refreshing odds tabs
- storing mappings
- preserving VBA / macros
- housing control sheets and staging data

### Daily Workbook (`.xlsx`)
Used for:
- the current slate
- pricing review
- board-level game comparison
- selected-game drilldown
- spread / total distribution review

---

## Key Sheets

### `MarketMaker_Board`
Slate-wide pricing board for the current date.

Representative fields:
- Home Team
- Away Team
- Market Home Line
- Fair Home Line
- Home Edge
- Market Total
- Fair Total
- Total Edge
- Home Win %
- Home Cover %
- Over %
- Confidence

### `Inputs`
Selected-game input engine.

Representative fields:
- Expected Tempo
- Expected Home ORtg
- Expected Away ORtg
- Expected Home Pts
- Expected Away Pts
- Fair Home Margin
- Fair Home Line
- Fair Total

### `SpreadTotal`
Selected-game pricing view with:
- margin distribution curves
- total distribution curves
- alternate spread ladder
- alternate total ladder
- fair price ladder outputs

---

## Daily Local Workflow

This project is intended to be updated **locally from Terminal**, not manually rebuilt through GitHub.

Typical daily flow:

1. Refresh / replace:
   - `Odds_from_Odds_Api_Total`
   - `Odds_from_Odds_Api_Spread`

2. Save the macro-enabled control workbook.

3. Run the local extraction / build pipeline:
   - schedule extraction
   - KenPom pull
   - cache rebuild
   - `GameInputs.csv` rebuild
   - daily workbook rebuild

4. Run workbook cleanup / QA scripts.

5. Open the final daily workbook.

This makes the package usable as a **daily-updating local market-making tool**.

---

## Quality-Control Philosophy

The project should reject obviously bad market-maker outputs, including:

- non-half-point market spreads/totals
- canonical name mismatches
- blank `Inputs`
- sign-convention violations
- impossible probabilities
- absurd fair odds displays
- broken `SpreadTotal` formulas

---

## What This Project Demonstrates

This project is designed to demonstrate:

- sports-trading intuition
- market-maker style pricing logic
- basketball-specific modeling
- data integration from multiple sources
- daily-operational model maintenance
- sheet-level QA discipline
- ability to turn predictive inputs into tradable pricing outputs

---

## Current Limitations

This model is still improvable. Key future upgrades include:

- historical calibration / backtesting
- closing-line comparison
- true lineup / minutes engine
- game-specific volatility / variance modeling
- more explicit joint score-grid implementation in the visible workbook
- enhanced team total / player prop extensions

No predictive model should be marketed as guaranteeing perfect outcomes or guaranteed profits. The correct claim is that this is a **structured, explainable, and operationally useful pricing framework**.

---

## Next-Phase Enhancements

High-value next steps:

1. **Calibration / backtest report**
2. **Closing-line comparison**
3. **Lineup / availability engine**
4. **Variance model**
5. **Team total pricing**
6. **Decomposition panel**
7. **Automated QA gate before workbook release**

---

## Summary

This workbook package is meant to function as a:

- **daily NCAA basketball pricing engine**
- **market-maker style spread / total board**
- **portfolio project demonstrating trading-model construction**
- **local operational workflow that can be refreshed each day from terminal**

The strongest framing is:

> a basketball market-making and pricing workbook built around shared-pace, team-specific efficiency projection, and joint-score-distribution logic, with daily local refresh capability and tradable spread/total outputs.
