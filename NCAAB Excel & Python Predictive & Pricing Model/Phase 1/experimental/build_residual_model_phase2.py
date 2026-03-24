"""
build_residual_model_phase2.py  —  Phase 2: Market-Relative Residual Model
===========================================================================
Targets:
  spread_residual = actual_margin  - mkt_spread   (positive = home beat spread)
  total_residual  = actual_total   - mkt_total    (positive = went over)

Features (all known BEFORE game time, no leakage):
  edge_spread     = fair_spread - (-mkt_spread)   model vs market spread
  edge_total      = fair_total  - mkt_total        model vs market total
  fair_spread                                      model's raw spread
  fair_total                                       model's raw total
  abs_edge_spread                                  |model - market| on spread
  abs_edge_total                                   |model - market| on total
  p_ml_home                                        model win probability
  p_home_cover                                     model cover probability
  p_over                                           model over probability
  is_neutral      = VENUE != H/R
  mkt_spread                                       market spread level
  mkt_total                                        market total level

Evaluation (leakage-safe):
  TimeSeriesSplit(5) OOF — chronological, no future leakage

Prints:
  Residual model OOF R², MAE, correlation
  ATS bucket table using residual model signals
  TOT bucket table using residual model signals
  Improvement vs Phase 1 baseline

Usage:
  python3 build_residual_model_phase2.py \\
      --pred cbb_cache/historical_p230_predictions.csv \\
      --out  cbb_cache/residual_model_phase2.csv
"""
from __future__ import annotations
import argparse, logging
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, GradientBoostingClassifier
from sklearn.linear_model import Ridge, LogisticRegression
from sklearn.metrics import (mean_absolute_error, r2_score,
                             roc_auc_score, brier_score_loss)
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import StandardScaler
from sklearn.isotonic import IsotonicRegression

logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
log = logging.getLogger("phase2")

VIG_MULT = 100.0/110.0
VIG_BE   = 1.0/(1.0+VIG_MULT)

def ats_ev(cr): return round(cr*VIG_MULT-(1.0-cr),4)

FEATURES_SPREAD = [
    "edge_spread","fair_spread","abs_edge_spread",
    "p_ml_home","p_home_cover","mkt_spread","is_neutral"
]
FEATURES_TOTAL = [
    "edge_total","fair_total","abs_edge_total",
    "p_over","mkt_total","is_neutral"
]

def build_features(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["edge_spread"]    = d["fair_spread"] - (-d["mkt_spread"])
    d["edge_total"]     = d["fair_total"]  -   d["mkt_total"]
    d["abs_edge_spread"]= d["edge_spread"].abs()
    d["abs_edge_total"] = d["edge_total"].abs()
    d["is_neutral"]     = (d["VENUE"] != "H/R").astype(float)
    d["spread_residual"]= d["actual_margin"] - (-d["mkt_spread"])
    d["total_residual"] = d["actual_total"]  -   d["mkt_total"]
    d["home_covered"]   = d["home_covered"].astype(float)
    d["over"]           = d["over"].astype(float)
    return d

def oof_regression(X, y, dates, model_fn):
    tss = TimeSeriesSplit(n_splits=5)
    oof = np.full(len(y), np.nan)
    idx = np.argsort(dates)
    X_s, y_s = X[idx], y[idx]
    for tr, te in tss.split(X_s):
        if len(tr) < 30: continue
        m = model_fn(); m.fit(X_s[tr], y_s[tr])
        oof[idx[te]] = m.predict(X_s[te])
    return oof

def oof_classification(X, y, dates, model_fn):
    tss = TimeSeriesSplit(n_splits=5)
    oof = np.full(len(y), np.nan)
    idx = np.argsort(dates)
    X_s, y_s = X[idx], y[idx]
    for tr, te in tss.split(X_s):
        if len(tr) < 30: continue
        m = model_fn(); m.fit(X_s[tr], y_s[tr])
        oof[idx[te]] = m.predict_proba(X_s[te])[:,1]
    return oof

def edge_bucket_table(df, chosen_col, label):
    p = df.dropna(subset=["mkt_spread",chosen_col]).copy()
    p["abs_edge"] = p["edge_spread"].abs()
    p["bucket"] = pd.cut(p["abs_edge"],bins=[0,1.5,3,5,99],
                         labels=["0-1.5","1.5-3","3-5",">5"])
    bkt = p.groupby("bucket",observed=True).agg(
        n=(chosen_col,"count"),
        cover_rate=(chosen_col,"mean")
    ).reset_index()
    bkt["ev"] = bkt["cover_rate"].apply(ats_ev)
    bkt["beats_vig"] = bkt["cover_rate"] > VIG_BE
    bkt["label"] = label
    return bkt

def tot_bucket_table(df, chosen_col, edge_col, label):
    p = df.dropna(subset=[edge_col, chosen_col]).copy()
    p["abs_edge"] = p[edge_col].abs()
    p["bucket"] = pd.cut(p["abs_edge"],bins=[0,2,4,6,99],
                         labels=["0-2","2-4","4-6",">6"])
    bkt = p.groupby("bucket",observed=True).agg(
        n=(chosen_col,"count"),
        over_rate=(chosen_col,"mean")
    ).reset_index()
    bkt["ev"] = bkt["over_rate"].apply(ats_ev)
    bkt["beats_vig"] = bkt["over_rate"] > VIG_BE
    bkt["label"] = label
    return bkt

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred", default="cbb_cache/historical_p230_predictions.csv")
    ap.add_argument("--out",  default="cbb_cache/residual_model_phase2.csv")
    args = ap.parse_args()

    raw = pd.read_csv(args.pred, parse_dates=["DATE"])
    hr  = raw[raw["VENUE"]=="H/R"].copy()
    hr  = hr.dropna(subset=["actual_margin","actual_total","mkt_spread","mkt_total"])
    log.info(f"H/R games with results: {len(hr)}")

    df = build_features(hr).sort_values("DATE").reset_index(drop=True)
    dates = df["DATE"].values

    log.info("\n" + "="*60)
    log.info("PHASE 2A — SPREAD RESIDUAL MODEL (GBM)")
    log.info("="*60)

    Xs = df[FEATURES_SPREAD].fillna(0).values
    ys = df["spread_residual"].values

    gbm_sp = lambda: GradientBoostingRegressor(
        n_estimators=200, max_depth=3, learning_rate=0.05,
        subsample=0.8, min_samples_leaf=10, random_state=42)
    ridge_sp = lambda: Ridge(alpha=1.0)

    oof_gbm_sp  = oof_regression(Xs, ys, dates, gbm_sp)
    oof_ridge_sp= oof_regression(Xs, ys, dates, ridge_sp)

    mask_sp = ~np.isnan(oof_gbm_sp)
    r2_gbm   = r2_score(ys[mask_sp], oof_gbm_sp[mask_sp])
    mae_gbm  = mean_absolute_error(ys[mask_sp], oof_gbm_sp[mask_sp])
    cor_gbm  = np.corrcoef(ys[mask_sp], oof_gbm_sp[mask_sp])[0,1]
    r2_ridge = r2_score(ys[mask_sp], oof_ridge_sp[mask_sp])
    mae_ridge= mean_absolute_error(ys[mask_sp], oof_ridge_sp[mask_sp])
    cor_ridge= np.corrcoef(ys[mask_sp], oof_ridge_sp[mask_sp])[0,1]

    log.info(f"  {'Model':<12} {'R²':>8} {'MAE':>8} {'Corr':>8}")
    log.info(f"  {'-'*40}")
    log.info(f"  {'GBM':<12} {r2_gbm:>8.4f} {mae_gbm:>8.3f} {cor_gbm:>8.4f}")
    log.info(f"  {'Ridge':<12} {r2_ridge:>8.4f} {mae_ridge:>8.3f} {cor_ridge:>8.4f}")
    log.info(f"  {'Baseline(0)':<12} {0:>8.4f} {mean_absolute_error(ys,np.zeros_like(ys)):>8.3f} {0:>8.4f}")

    # Use GBM residual to choose side
    df["oof_spread_resid"] = oof_gbm_sp
    df["resid_bet_home"] = df["oof_spread_resid"] > 0
    df["resid_chosen_cover"] = np.where(
        df["resid_bet_home"], df["home_covered"], 1-df["home_covered"])

    # Phase 1 baseline: edge_spread > 0
    df["p1_bet_home"] = df["edge_spread"] > 0
    df["p1_chosen_cover"] = np.where(
        df["p1_bet_home"], df["home_covered"], 1-df["home_covered"])

    log.info("\n" + "="*60)
    log.info("PHASE 2B — TOTAL RESIDUAL MODEL (GBM)")
    log.info("="*60)

    Xt = df[FEATURES_TOTAL].fillna(0).values
    yt = df["total_residual"].values

    gbm_tt = lambda: GradientBoostingRegressor(
        n_estimators=200, max_depth=3, learning_rate=0.05,
        subsample=0.8, min_samples_leaf=10, random_state=42)

    oof_gbm_tt = oof_regression(Xt, yt, dates, gbm_tt)
    mask_tt = ~np.isnan(oof_gbm_tt)
    r2_tt  = r2_score(yt[mask_tt], oof_gbm_tt[mask_tt])
    mae_tt = mean_absolute_error(yt[mask_tt], oof_gbm_tt[mask_tt])
    cor_tt = np.corrcoef(yt[mask_tt], oof_gbm_tt[mask_tt])[0,1]

    log.info(f"  {'Model':<12} {'R²':>8} {'MAE':>8} {'Corr':>8}")
    log.info(f"  {'-'*40}")
    log.info(f"  {'GBM':<12} {r2_tt:>8.4f} {mae_tt:>8.3f} {cor_tt:>8.4f}")
    log.info(f"  {'Baseline(0)':<12} {0:>8.4f} {mean_absolute_error(yt,np.zeros_like(yt)):>8.3f} {0:>8.4f}")

    df["oof_total_resid"] = oof_gbm_tt
    df["resid_bet_over"]  = df["oof_total_resid"] > 0
    df["resid_chosen_over"] = np.where(
        df["resid_bet_over"], df["over"], 1-df["over"])
    df["p1_bet_over"] = df["edge_total"] > 0
    df["p1_chosen_over"] = np.where(
        df["p1_bet_over"], df["over"], 1-df["over"])

    log.info("\n" + "="*65)
    log.info("ATS EDGE BUCKET COMPARISON (H/R, side-aware)")
    log.info(f"  Breakeven={VIG_BE:.4%}")
    log.info("="*65)
    p1_sp  = edge_bucket_table(df[mask_sp], "p1_chosen_cover",    "Phase1 (fair-vs-mkt)")
    p2_sp  = edge_bucket_table(df[mask_sp], "resid_chosen_cover", "Phase2 (residual GBM)")
    all_sp = pd.concat([p1_sp, p2_sp])
    log.info(f"  {'Version':<25} {'Bucket':<12} {'N':>5} {'Cover%':>8} {'EV@-110':>9} {'Vig':>5} {'N>=150':>7}")
    log.info(f"  {'-'*70}")
    for _,r in all_sp.iterrows():
        log.info(f"  {str(r['label']):<25} {str(r['bucket']):<12} {r['n']:>5} "
                 f"{r['cover_rate']:>8.3f} {r['ev']:>9.4f} "
                 f"{'✓' if r['beats_vig'] else '':>5} {'YES' if r['n']>=150 else 'no':>7}")

    log.info("\n" + "="*65)
    log.info("TOTALS EDGE BUCKET COMPARISON (|model_edge|)")
    log.info("="*65)
    p1_tt  = tot_bucket_table(df[mask_tt], "p1_chosen_over",    "edge_total", "Phase1")
    p2_tt  = tot_bucket_table(df[mask_tt], "resid_chosen_over", "oof_total_resid", "Phase2")
    all_tt = pd.concat([p1_tt, p2_tt])
    log.info(f"  {'Version':<12} {'Bucket':<8} {'N':>5} {'Over%':>7} {'EV@-110':>9} {'Vig':>5} {'N>=150':>7}")
    log.info(f"  {'-'*55}")
    for _,r in all_tt.iterrows():
        log.info(f"  {str(r['label']):<12} {str(r['bucket']):<8} {r['n']:>5} "
                 f"{r['over_rate']:>7.3f} {r['ev']:>9.4f} "
                 f"{'✓' if r['beats_vig'] else '':>5} {'YES' if r['n']>=150 else 'no':>7}")

    # Classification AUC comparison
    log.info("\n" + "="*65)
    log.info("ATS AUC: Phase 1 (p_home_cover) vs Phase 2 (residual → prob)")
    log.info("="*65)
    # Convert residual to pseudo-probability via logistic
    sc = StandardScaler()
    Xc = sc.fit_transform(df[["oof_spread_resid"]].fillna(0))
    oof_p2_ats = oof_classification(Xc, df["home_covered"].values, dates,
        lambda: LogisticRegression(C=1.0, solver="lbfgs"))
    mask_c = ~np.isnan(oof_p2_ats) & mask_sp
    p1_auc = roc_auc_score(df["home_covered"].values[mask_c],
                           df["p_home_cover"].values[mask_c])
    p2_auc = roc_auc_score(df["home_covered"].values[mask_c],
                           oof_p2_ats[mask_c])
    log.info(f"  Phase 1 p_home_cover AUC: {p1_auc:.4f}")
    log.info(f"  Phase 2 residual→logit AUC: {p2_auc:.4f}")
    log.info(f"  ΔAUC: {p2_auc-p1_auc:+.4f}")

    # Feature importance
    log.info("\n" + "="*60)
    log.info("FEATURE IMPORTANCE (GBM spread residual)")
    log.info("="*60)
    full_gbm = GradientBoostingRegressor(n_estimators=200, max_depth=3,
        learning_rate=0.05, subsample=0.8, min_samples_leaf=10, random_state=42)
    full_gbm.fit(Xs, ys)
    for feat, imp in sorted(zip(FEATURES_SPREAD, full_gbm.feature_importances_),
                             key=lambda x:-x[1]):
        bar = "█" * int(imp*50)
        log.info(f"  {feat:<20} {imp:.4f}  {bar}")

    # Save
    df.to_csv(args.out, index=False)
    log.info(f"\nWritten: {args.out}  ({len(df)} games)")
    log.info("\nDECISION RULE:")
    log.info("  Phase 2 improves on Phase 1 if:")
    log.info("  (a) ΔAUC >= +0.015 on ATS, OR")
    log.info("  (b) residual model produces N>=150 bucket with positive EV")
    log.info("      where Phase 1 did not, OR")
    log.info("  (c) R² on spread residual > 0 (model beats naive 0-prediction)")

if __name__ == "__main__":
    main()
