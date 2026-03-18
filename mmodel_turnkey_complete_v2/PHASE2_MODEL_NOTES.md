# Phase 2 Model Notes

## Blended team ratings

The current upstream production input builder uses:

- 60% KenPom adjusted ratings
- 25% season raw team-feed ratings
- 15% recent / last-10 raw team-feed ratings

This produces:

- BLEND_ADJ_OE
- BLEND_ADJ_DE
- BLEND_TEMPO

## Tempo

Expected tempo is computed as:

ExpectedTempo
= 0.85 * harmonic_mean(HomeTempo, AwayTempo)
+ 0.15 * LeagueAvgTempo
+ HomeTempoAdj
+ AwayTempoAdj

where the harmonic mean is:

2 / (1/HomeTempo + 1/AwayTempo)

## Expected ORtg

Home:

ExpHomeORtg
= LeagueAvgOE
+ 0.55 * (HomeOE - LeagueAvgOE)
+ 0.45 * (AwayDE - LeagueAvgDE)
+ SiteAdj
+ RotationAdj
+ ManualPlayerAdj

Away:

ExpAwayORtg
= LeagueAvgOE
+ 0.55 * (AwayOE - LeagueAvgOE)
+ 0.45 * (HomeDE - LeagueAvgDE)
- SiteAdj
+ RotationAdj
+ ManualPlayerAdj

Higher DE means worse defense.
Lower DE means better defense.

## Expected points

ExpectedHomePoints = ExpectedTempo * ExpHomeORtg / 100
ExpectedAwayPoints = ExpectedTempo * ExpAwayORtg / 100

FairHomeMargin = ExpectedHomePoints - ExpectedAwayPoints
FairTotal = ExpectedHomePoints + ExpectedAwayPoints

## Joint PMF

Phase 2 builds a discrete exact score grid over:

P(HomePts = x, AwayPts = y)

using a shared latent tempo / game-state structure.

From that joint grid it derives:

- exact home win probability
- exact home cover probability
- exact over probability
- exact margin PMF
- exact total PMF

## Important scope note

This Phase 2 engine is structurally valid and normalized, but it is not yet fully calibrated from historical closes and results.
