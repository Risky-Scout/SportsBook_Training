# Phase 2 — Exact Joint PMF Research Engine

This module adds a parallel exact-score probability engine for the NCAAB market-maker workflow.

## Purpose

The production baseline currently uses:
- blended team expectation modeling
- shared-tempo expected points
- normal-approximation pricing for spread and total curves

Phase 2 adds:
- an exact discrete joint score grid for each game
- exact margin PMFs
- exact total PMFs
- game-level exact win / cover / over probabilities

## Core outputs

For each slate date, the engine writes:

- `outputs/exact_pmf_game_summary_<date>.csv`
- `outputs/exact_margin_pmf_<date>.csv`
- `outputs/exact_total_pmf_<date>.csv`
- `outputs/grids/exact_score_grid_<game>.csv`

## Inputs

The engine reads:

- `../cbb_cache/GameInputs.csv`
- `../cbb_cache/BlendedRatings.csv`
- `./exact_pmf_params_v2.json`

## Mathematical structure

For each game:

1. Recompute expected tempo
2. Recompute expected home and away ORtg
3. Convert those into expected home and away points
4. Build a discrete joint score distribution

The engine outputs a joint distribution:

P(HomePts = x, AwayPts = y)

and derives exact margin and total PMFs from that grid.

## What has been verified

- all score-grid PMFs sum to 1
- margin PMFs sum to 1 by game
- total PMFs sum to 1 by game
- expected points reconcile to fair margin and fair total

## What is still future work

- historical calibration of dispersion and correlation
- backtest against results and closing lines
- direct workbook injection as the primary pricing layer
- richer lineup / availability modeling
