# NCAAB Pregame Market Pricing Engine

A Python-based pricing engine for NCAA men's basketball that generates fair spreads, totals, and moneyline probabilities from first principles. Built by Joseph Shackelford, ASA MAAA.

## What it does

The model prices each game by constructing an expected scoring distribution for both teams, then deriving market-relative edge from the resulting joint probability mass function. It is designed to identify games where the market spread or total is meaningfully different from the model's fair price.

## How it works

Each team's offensive rating is built from three sources blended together: KenPom's opponent-adjusted efficiency ratings as the prior, BigDataBall rolling season averages as the form signal, and current four-factor data (eFG%, turnover rate, offensive rebounding, free throw rate) as the matchup layer. The four factors enter the core offensive rating directly — they are not a post-hoc adjustment.

The scoring model uses a Negative Binomial PMF with pace-adjusted means and a Gauss-Hermite quadrature integration over tempo uncertainty. From the joint home/away scoring distribution, the model reads off the fair spread, fair total, moneyline probability, cover probability, and over probability directly.

Calibration is fit on 5,000+ historical H/R games using isotonic regression in chronological cross-validation folds.

## Stack

- Python 3.9
- KenPom API (efficiency ratings, four factors, pace)
- BigDataBall (rolling box score baselines)
- openpyxl, pandas, scipy, scikit-learn

## Structure
```
model/          pricing engine and data pipeline scripts
validation/     holdout audit, ablation tests, subset diagnostics
outputs/        dated production workbooks
```

## Results

On 5,001 historical H/R games: corr(fair_spread, -market_spread) = 0.89, MAD vs market = 2.8 pts. ATS signal present in the >5-point edge bucket.
