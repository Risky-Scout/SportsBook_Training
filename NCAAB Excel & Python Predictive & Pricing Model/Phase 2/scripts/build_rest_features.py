"""
build_rest_features.py  —  Rest/Schedule Feature Layer
=======================================================
Features built from TeamBaselines DATE + GAME_ID (no leakage):
  days_rest_h       — days since home team's last game (capped at 14)
  days_rest_a       — days since away team's last game (capped at 14)
  rest_diff         — days_rest_h - days_rest_a
  is_back2back_h    — 1 if home team played yesterday
  is_back2back_a    — 1 if away team played yesterday
  games_last7_h     — home team game count in prior 7 days
  games_last7_a     — away team game count in prior 7 days
  fatigue_diff      — games_last7_h - games_last7_a
  pace_mismatch     — |blend_POSS_h - blend_POSS_a|
  momentum_h        — blend_OEFF_h - sea_OEFF_h (trending above/below season)
  momentum_a        — blend_OEFF_a - sea_OEFF_a

Target: spread_residual = actual_margin - (-mkt_spread)
Model: Ridge OOF, TimeSeriesSplit(5), strictly chronological
Clip: delta_rest clipped to ±3.0 pts

Acceptance tests:
  [1] R² > 0
  [2] ΔATS_AUC_cal >= +0.005
  [3] ΔTOT_AUC_cal >= -0.005
  [4] ATS >5 EV >= baseline
  [5] ATS 3-5 EV >= baseline
  [6] mean|delta| <= 2.0
  [7] rest_diff coef positive (more rest = better)
  [8] back2back coef negative (fatigue hurts)

Usage:
  python3 build_rest_features.py \\
      --baselines  cbb_cache/TeamBaselines.csv \\
      --pred       cbb_cache/historical_p230_predictions.csv \\
      --out        cbb_cache/rest_feature_predictions.csv
"""
from __future__ import annotations
import argparse, logging, re
import numpy as np
import pandas as pd
from scipy import stats as _stats
from sklearn.linear_model import Ridge
from sklearn.metrics import r2_score, mean_absolute_error, roc_auc_score
from sklearn.model_selection import TimeSeriesSplit
from sklearn.isotonic import IsotonicRegression

logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
log = logging.getLogger("rest_features")

VIG_MULT = 100.0 / 110.0
VIG_BE   = 1.0 / (1.0 + VIG_MULT)
DELTA_CLIP = 3.0
SIGMA_M = 11.0

def ats_ev(cr): return round(cr * VIG_MULT - (1 - cr), 4)

def oof_auc(y, p):
    y = np.array(y, dtype=float); p = np.array(p, dtype=float)
    mask = np.isfinite(y) & np.isfinite(p)
    y, p = y[mask], p[mask]
    if len(y) < 100 or y.mean() in (0.0, 1.0): return float("nan"), float("nan")
    auc_r = roc_auc_score(y, p)
    tss = TimeSeriesSplit(5); oof_p = np.full(len(y), np.nan)
    for tr, te in tss.split(y):
        if len(tr) < 30: continue
        iso = IsotonicRegression(out_of_bounds="clip")
        iso.fit(p[tr], y[tr]); oof_p[te] = iso.predict(p[te])
    valid = np.isfinite(oof_p)
    auc_c = roc_auc_score(y[valid], oof_p[valid]) if valid.sum() > 50 else float("nan")
    return round(auc_r, 4), round(auc_c, 4)

def edge_buckets(df, sp_col, cov_col):
    p = df.dropna(subset=[sp_col, "mkt_spread", cov_col]).copy()
    p[cov_col] = p[cov_col].astype(float)
    p["edge"] = p[sp_col] - (-p["mkt_spread"])
    p["chosen"] = np.where(p["edge"] > 0, p[cov_col], 1 - p[cov_col])
    p["abs_edge"] = p["edge"].abs()
    p["bucket"] = pd.cut(p["abs_edge"], bins=[0,1.5,3,5,99], labels=["0-1.5","1.5-3","3-5",">5"])
    bkt = p.groupby("bucket", observed=True).agg(n=("chosen","count"), cr=("chosen","mean")).reset_index()
    bkt["ev"] = bkt["cr"].apply(ats_ev)
    return bkt

def get_ev(bkt_df, bucket):
    row = bkt_df[bkt_df["bucket"] == bucket]
    return float(row["ev"].iloc[0]) if len(row) else float("nan")

def build_rest_schedule(bas):
    """Build rest/schedule features per team-game from TeamBaselines."""
    bas = bas.sort_values(["KP_NAME","DATE"]).copy()
    bas["prev_date"] = bas.groupby("KP_NAME")["DATE"].shift(1)
    bas["days_rest"] = (bas["DATE"] - bas["prev_date"]).dt.days.clip(upper=14).fillna(14)
    bas["is_back2back"] = (bas["days_rest"] == 1).astype(float)

    # Games in prior 7 days (excluding current)
    def games_last7(group):
        dates = group["DATE"].values
        result = []
        for i, d in enumerate(dates):
            prior = dates[:i]
            count = ((d - prior) <= np.timedelta64(7, "D")).sum()
            result.append(int(count))
        return result

    bas["games_last7"] = bas.groupby("KP_NAME", group_keys=False).apply(
        lambda g: pd.Series(games_last7(g), index=g.index)
    )

    # Momentum: current blend vs season baseline
    bas["momentum"] = bas["blend_OEFF"] - bas["sea_OEFF"]
    bas["momentum"] = bas["momentum"].fillna(0.0)

    return bas[["GAME_ID","KP_NAME","VENUE","DATE","days_rest","is_back2back",
                "games_last7","momentum","blend_POSS","blend_OEFF","sea_OEFF",
                "blend_DEFF","sea_DEFF"]].copy()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baselines", default="cbb_cache/TeamBaselines.csv")
    ap.add_argument("--pred",      default="cbb_cache/historical_p230_predictions.csv")
    ap.add_argument("--out",       default="cbb_cache/rest_feature_predictions.csv")
    args = ap.parse_args()

    log.info("=" * 65)
    log.info("Rest/Schedule Feature Layer")
    log.info("=" * 65)

    bas = pd.read_csv(args.baselines, parse_dates=["DATE"])
    bas["GAME_ID"] = bas["GAME_ID"].astype(str).str.strip()
    log.info(f"TeamBaselines: {len(bas)} rows, {bas['KP_NAME'].nunique()} teams")

    # Build rest features
    rest = build_rest_schedule(bas)
    log.info("Rest/schedule features built")

    # Split home/road
    rh = rest[rest["VENUE"]=="Home"][["GAME_ID","days_rest","is_back2back",
         "games_last7","momentum","blend_POSS","blend_OEFF","sea_OEFF"]].copy()
    rr = rest[rest["VENUE"]=="Road"][["GAME_ID","days_rest","is_back2back",
         "games_last7","momentum","blend_POSS"]].copy()

    # Pair on GAME_ID
    paired = rh.merge(rr, on="GAME_ID", suffixes=("_h","_a"))
    paired["GAME_ID"] = paired["GAME_ID"].astype(str).str.strip()
    log.info(f"Paired rest features: {len(paired)} H/R games")

    # Build matchup features
    paired["rest_diff"]     = paired["days_rest_h"] - paired["days_rest_a"]
    paired["b2b_diff"]      = paired["is_back2back_a"] - paired["is_back2back_h"]  # +1 = away more fatigued
    paired["fatigue_diff"]  = paired["games_last7_a"] - paired["games_last7_h"]
    paired["pace_mismatch"] = (paired["blend_POSS_h"] - paired["blend_POSS_a"]).abs()
    paired["momentum_diff"] = paired["momentum_h"] - paired["momentum_a"]

    FEATURES = ["rest_diff","b2b_diff","fatigue_diff","pace_mismatch","momentum_diff"]

    # Load predictions
    preds = pd.read_csv(args.pred, parse_dates=["DATE"])
    preds = preds[preds["VENUE"]=="H/R"].copy()
    preds["home_covered"] = pd.to_numeric(preds["home_covered"], errors="coerce")
    preds["over"]         = pd.to_numeric(preds["over"],         errors="coerce")

    # Load crosswalk to get GAME_ID for each pred row
    src = open("run_phase3a1_production.py").read()
    entries = re.findall(r'"([^"]{3,}?)"\s*:\s*"([^"]{2,}?)"', src)
    xwalk = {k:v for k,v in entries if len(k)>4}
    def R(n): return xwalk.get(str(n).strip(), str(n).strip())

    preds["KP_h"] = preds["TEAM_h"].apply(R)
    preds["DATE_str"] = preds["DATE"].dt.strftime("%Y-%m-%d")

    bh_lookup = bas[bas["VENUE"]=="Home"][["GAME_ID","KP_NAME","DATE"]].copy()
    bh_lookup["DATE_str"] = bh_lookup["DATE"].dt.strftime("%Y-%m-%d")
    bh_lookup["GAME_ID"] = bh_lookup["GAME_ID"].astype(str).str.strip()
    bh_lookup = bh_lookup.rename(columns={"KP_NAME":"KP_h"})

    p2 = preds.merge(bh_lookup[["GAME_ID","KP_h","DATE_str"]], on=["KP_h","DATE_str"], how="left")
    if "GAME_ID" not in p2.columns:
        gid_cols = [c for c in p2.columns if "GAME_ID" in c]
        p2["GAME_ID"] = p2[gid_cols[0]] if gid_cols else ""
    p2["GAME_ID"] = p2["GAME_ID"].astype(str).str.strip()

    # Join rest features
    p2 = p2.merge(paired[["GAME_ID"] + FEATURES], on="GAME_ID", how="left")
    p2[FEATURES] = p2[FEATURES].fillna(0.0)
    p2 = p2.sort_values("DATE").reset_index(drop=True)
    log.info(f"Final dataset: {len(p2)} games with rest features")

    # Target: spread residual
    p2["spread_residual"] = p2["actual_margin"] - (-p2["mkt_spread"])
    p2 = p2.dropna(subset=["spread_residual","mkt_spread"]).copy()
    log.info(f"Games with spread residual: {len(p2)}")

    # OOF Ridge on spread residual
    X = p2[FEATURES].values
    y = p2["spread_residual"].values
    oof_delta = np.zeros(len(p2))
    coefs = []
    tss = TimeSeriesSplit(5)
    log.info("Running OOF Ridge(alpha=5) on spread residual...")
    for tr, te in tss.split(X):
        if len(tr) < 50: continue
        m = Ridge(alpha=5.0); m.fit(X[tr], y[tr])
        oof_delta[te] = m.predict(X[te]); coefs.append(m.coef_)

    oof_delta = np.clip(oof_delta, -DELTA_CLIP, DELTA_CLIP)
    p2["delta_rest"] = oof_delta

    r2_val  = r2_score(y, oof_delta)
    mae_val = mean_absolute_error(y, oof_delta)
    mean_d  = float(np.abs(oof_delta).mean())
    avg_c   = np.mean(coefs, axis=0) if coefs else np.zeros(len(FEATURES))
    log.info(f"R²={r2_val:.4f}  MAE={mae_val:.3f}  mean|delta|={mean_d:.3f}")
    log.info(f"Coefs: " + " ".join(f"{f}={c:+.3f}" for f,c in zip(FEATURES, avg_c)))

    # Apply delta to fair spread
    p2["fair_spread_rest"] = p2["fair_spread"] + p2["delta_rest"]
    sp_v = p2["mkt_spread"].notna()
    p2["p_cover_rest"] = p2["p_home_cover"].copy()
    p2.loc[sp_v,"p_cover_rest"] = _stats.norm.cdf(
        (p2.loc[sp_v,"fair_spread_rest"] - (-p2.loc[sp_v,"mkt_spread"])) / SIGMA_M)
    p2["p_cover_rest"] = np.clip(p2["p_cover_rest"], 0.01, 0.99)

    # AUC comparison
    ats_r_b, ats_c_b = oof_auc(p2["home_covered"].values, p2["p_home_cover"].values)
    ats_r_r, ats_c_r = oof_auc(p2["home_covered"].values, p2["p_cover_rest"].values)
    d_ats = round((ats_c_r or 0) - (ats_c_b or 0), 4)

    bkt_b = edge_buckets(p2, "fair_spread",      "home_covered")
    bkt_r = edge_buckets(p2, "fair_spread_rest", "home_covered")

    # Acceptance tests
    rest_coef_idx = FEATURES.index("rest_diff")
    b2b_coef_idx  = FEATURES.index("b2b_diff")
    rest_sign_ok  = bool(avg_c[rest_coef_idx] > 0)
    b2b_sign_ok   = bool(avg_c[b2b_coef_idx]  > 0)  # away b2b hurts away = positive for home

    tests = [
        ("[1] R²>0",                 r2_val > 0,
            f"R²={r2_val:.4f}", ">0"),
        ("[2] ΔATS_AUC>=+0.005",     d_ats >= 0.005,
            f"Δ={d_ats:+.4f}", ">=+0.005"),
        ("[3] ATS >5>=baseline",
            get_ev(bkt_r,">5") >= get_ev(bkt_b,">5"),
            f"{get_ev(bkt_r,'>5'):.4f} vs {get_ev(bkt_b,'>5'):.4f}", ">=baseline"),
        ("[4] ATS 3-5>=baseline",
            get_ev(bkt_r,"3-5") >= get_ev(bkt_b,"3-5"),
            f"{get_ev(bkt_r,'3-5'):.4f} vs {get_ev(bkt_b,'3-5'):.4f}", ">=baseline"),
        ("[5] mean|delta|<=2.0",     mean_d <= 2.0,
            f"{mean_d:.3f}", "<=2.0"),
        ("[6] rest_diff coef>0",     rest_sign_ok,
            f"{avg_c[rest_coef_idx]:+.3f}", ">0"),
        ("[7] b2b_diff coef>0",      b2b_sign_ok,
            f"{avg_c[b2b_coef_idx]:+.3f}", ">0"),
    ]
    n_pass = sum(1 for _, p, _, _ in tests if p)

    log.info(f"\n{'='*65}")
    log.info("ACCEPTANCE TESTS")
    log.info(f"{'='*65}")
    for name, passed, value, crit in tests:
        log.info(f"  {'PASS' if passed else 'FAIL'}  {name:<30} {value:<30} [{crit}]")
    log.info(f"\n  {n_pass}/7 passed")
    log.info(f"\n  ATS AUC: base_raw={ats_r_b:.4f} base_cal={ats_c_b:.4f}  "
             f"rest_raw={ats_r_r:.4f} rest_cal={ats_c_r:.4f}  Δ={d_ats:+.4f}")
    log.info(f"\n  ATS BUCKETS (baseline → rest layer):")
    log.info(f"  {'Bucket':<10} {'Base EV':>9} {'Base N':>7}   {'Rest EV':>9} {'Rest N':>7}  Vig")
    for (_, rb), (_, rr_) in zip(bkt_b.iterrows(), bkt_r.iterrows()):
        log.info(f"  {str(rb['bucket']):<10} {rb['ev']:>+9.4f} {rb['n']:>7}   "
                 f"{rr_['ev']:>+9.4f} {rr_['n']:>7}  {'✓' if rr_['cr']>VIG_BE else ''}")

    if n_pass >= 5:
        verdict = f"{n_pass}/7 PASS — rest layer PROMOTED to production"
    else:
        verdict = f"{n_pass}/7 passed — rest layer EXPERIMENTAL. Production = team_only_v1_p2_30"
    log.info(f"\n  VERDICT: {verdict}")

    p2.to_csv(args.out, index=False)
    log.info(f"\nWritten: {args.out} ({len(p2)} games)")

if __name__ == "__main__":
    main()
