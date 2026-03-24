# Phase 2 — Residual Model Research

**Status:** In development. No Phase 2 layer has been promoted to production.  
**Production model:** Phase 1 `team_only_v1_p2_30` — unchanged.

---

## What Phase 2 is trying to solve

Phase 1 produces clean, auditable fair prices from a joint NB PMF engine using KenPom efficiency priors and BDB rolling baselines. It has measurable ATS signal in two buckets (1.5–3 and >5) but overall AUC of 0.52 — meaning the base pricing model leaves residual structure unexplained.

Phase 2 attempts to capture that residual structure through additional feature layers that sit on top of Phase 1 outputs. Phase 1 is never modified.

---

## Architecture
```
Phase 1 output (MatchupLatents CSV)
        ↓
Phase 2 residual layer (reads Phase 1, adds corrections)
        ↓
Phase 2 output (fair_spread_p2, fair_total_p2, delta columns)
```

Phase 2 scripts read `cbb_cache/historical_p230_predictions.csv` as input. They do not modify any Phase 1 script or cache file.

---

## Experiments

### Market-relative residual model (`experimental/build_residual_model_phase2.py`)
**Status: Failed — experimental only**

Target: `actual_margin − mkt_spread`  
Features: `edge_spread`, `fair_spread`, `abs_edge_spread`, `p_ml_home`, `p_home_cover`, `mkt_spread`  
Result: GBM R²=−0.036, Ridge R²=−0.002. Both worse than naive baseline. ΔAUC=−0.029.  
Cause: 728-game sample (pre-fix) insufficient for GBM. After fix to 5,001 games, results improved marginally but did not meet promotion threshold.

### Four-factor residual layer (`experimental/build_ff_residual_layer.py`)
**Status: Failed — experimental only. Historical validation blocked.**

Target: `actual_OEFF − base_ortg`  
Features: matchup z-score four factors (eFG, TOV, ORB, FTR) offense vs defense  
Result: R²=−0.016, eFG coefficient sign wrong (−3.051 instead of positive), 6/9 acceptance tests failed.  
Root cause: KenPom archives contain only `AdjOE`, `AdjDE`, `AdjTempo`, `AdjEM` — no date-stamped four-factor columns. Using end-of-season FF or contaminated opponent-raw proxies would be dishonest. Historical FF validation is blocked until daily KenPom FF archives are collected.

**Honest statement:** Historical four-factor validation cannot be done because the available KenPom archive files do not contain date-stamped four-factor columns. The FF layer is available as a present-day research overlay only — not historically validated, not promoted.

### Rest/schedule feature layer (`scripts/build_rest_features.py`)
**Status: Built, pending OOF validation run**

Features (all leakage-safe, derived from DATE and GAME_ID in TeamBaselines):
- `days_rest_h`, `days_rest_a`, `rest_diff`
- `b2b_h`, `b2b_a`, `long_rest_h`, `long_rest_a`
- `games_last7_h`, `games_last7_a`
- `pace_mismatch = |blend_POSS_h − blend_POSS_a|`
- `oe_momentum_h/a = blend_OEFF − sea_OEFF`
- `de_momentum_h/a = blend_DEFF − sea_DEFF`

Targets: `actual_margin − fair_spread`, `actual_total − fair_total`  
Model: Ridge, TimeSeriesSplit(5), strictly chronological OOF

Promotion requires all 10 acceptance tests to pass:
1. Spread R² > 0
2. Total R² > 0
3. ΔATS_AUC_cal ≥ +0.010
4. ΔTOT_AUC_cal ≥ +0.010
5. ATS 3–5 EV ≥ baseline
6. ATS >5 EV ≥ baseline − 0.010
7. TOT 2–4 EV ≥ baseline
8. TOT 4–6 EV ≥ baseline − 0.010
9. mean|delta_spread| ≤ 1.5
10. mean|delta_total| ≤ 2.5

---

## Data constraints

| Constraint | Impact |
|---|---|
| KenPom archives lack FF columns | FF layer cannot be historically validated |
| Single season (2025–26) | ~5,001 H/R games — sufficient for Ridge, marginal for GBM |
| BDB defensive FF is contaminated proxy | Cannot use opponent raw offensive FF as defensive input |

## Next steps

1. Run `build_rest_features.py` and evaluate against 10 acceptance tests
2. Start collecting daily KenPom FF archives via `fetch_kenpom.py` for future FF validation
3. If rest features fail, evaluate pace-interaction and conference-level features
