"""
build_ff_residual_layer.py  —  Phase 2: Four-Factor Residual Layer
Exact spec. Final clean version.
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
log = logging.getLogger("ff_residual")

VIG_MULT = 100.0 / 110.0
VIG_BE   = 1.0 / (1.0 + VIG_MULT)
DELTA_CLIP = 3.0
SIGMA_M  = 11.0
SIGMA_T  = 18.0

def ats_ev(cr): return round(cr * VIG_MULT - (1 - cr), 4)

def oof_auc(y, p, n_splits=5):
    y = np.array(y, dtype=float); p = np.array(p, dtype=float)
    mask = np.isfinite(y) & np.isfinite(p)
    y, p = y[mask], p[mask]
    if len(y) < 100 or y.mean() in (0.0, 1.0):
        return float("nan"), float("nan")
    auc_r = roc_auc_score(y, p)
    tss = TimeSeriesSplit(n_splits); oof_p = np.full(len(y), np.nan)
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
    p["bucket"] = pd.cut(p["abs_edge"], bins=[0,1.5,3,5,99],
                         labels=["0-1.5","1.5-3","3-5",">5"])
    bkt = p.groupby("bucket", observed=True).agg(
        n=("chosen","count"), cr=("chosen","mean")).reset_index()
    bkt["ev"] = bkt["cr"].apply(ats_ev)
    return bkt

def tot_buckets(df, tt_col, ov_col):
    p = df.dropna(subset=[tt_col, "mkt_total", ov_col]).copy()
    p[ov_col] = p[ov_col].astype(float)
    p["edge"] = (p[tt_col] - p["mkt_total"]).abs()
    p["chosen"] = np.where(p[tt_col] > p["mkt_total"], p[ov_col], 1 - p[ov_col])
    p["bucket"] = pd.cut(p["edge"], bins=[0,2,4,6,99],
                         labels=["0-2","2-4","4-6",">6"])
    bkt = p.groupby("bucket", observed=True).agg(
        n=("chosen","count"), cr=("chosen","mean")).reset_index()
    bkt["ev"] = bkt["cr"].apply(ats_ev)
    return bkt

def get_ev(bkt_df, bucket):
    row = bkt_df[bkt_df["bucket"] == bucket]
    return float(row["ev"].iloc[0]) if len(row) else float("nan")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baselines",  default="cbb_cache/TeamBaselines.csv")
    ap.add_argument("--pred",       default="cbb_cache/historical_p230_predictions.csv")
    ap.add_argument("--team-feed",  default="feeds_daily/03-22-2026-cbb-season-team-feed.xlsx",
                    dest="team_feed")
    ap.add_argument("--out",        default="cbb_cache/ff_residual_predictions.csv")
    args = ap.parse_args()

    log.info("=" * 65)
    log.info("Four-Factor Residual Layer — Phase 2")
    log.info("=" * 65)

    # ── TeamBaselines ───────────────────────────────────────────────
    bas = pd.read_csv(args.baselines, parse_dates=["DATE"])
    bas["GAME_ID"] = bas["GAME_ID"].astype(str).str.strip()
    log.info(f"TeamBaselines: {len(bas)} rows, {bas['KP_NAME'].nunique()} teams")

    for stat in ["eFG","TOV","ORB","FTR"]:
        sea = bas[f"sea_g_{stat}"].fillna(bas[f"sea_g_{stat}"].mean())
        l10 = bas[f"L10_g_{stat}"].fillna(bas[f"L10_g_{stat}"].mean())
        l5  = bas[f"L5_g_{stat}"].fillna(bas[f"L5_g_{stat}"].mean())
        bas[f"bff_{stat}"] = 0.50*sea + 0.30*l10 + 0.20*l5
    log.info("Built blend_ff (0.50*sea + 0.30*L10 + 0.20*L5)")

    bh = bas[bas["VENUE"]=="Home"][["GAME_ID","KP_NAME","DATE",
        "bff_eFG","bff_TOV","bff_ORB","bff_FTR",
        "def_eFG_allowed","def_TOV_forced","def_DRB_rate","def_FTR_allowed",
        "blend_OEFF","blend_DEFF","blend_POSS"]].copy()
    br = bas[bas["VENUE"]=="Road"][["GAME_ID","KP_NAME",
        "bff_eFG","bff_TOV","bff_ORB","bff_FTR",
        "def_eFG_allowed","def_TOV_forced","def_DRB_rate","def_FTR_allowed",
        "blend_OEFF","blend_DEFF","blend_POSS"]].copy()

    # ── Actual OEFF from team feed ──────────────────────────────────
    log.info(f"Loading team feed: {args.team_feed}")
    tf = pd.read_excel(args.team_feed, engine="openpyxl")
    tf.columns = [str(c).replace("\n"," ").strip() for c in tf.columns]
    tf["DATE"] = pd.to_datetime(tf["DATE"], errors="coerce")
    tf["GAME-ID"] = tf["GAME-ID"].astype(str).str.strip()
    tf["OEFF"] = pd.to_numeric(tf["OEFF"], errors="coerce")
    tf["F"]    = pd.to_numeric(tf["F"],    errors="coerce")

    src = open("run_phase3a1_production.py").read()
    entries = re.findall(r'"([^"]{3,}?)"\s*:\s*"([^"]{2,}?)"', src)
    xwalk = {k:v for k,v in entries if len(k)>4}
    def R(n): return xwalk.get(str(n).strip(), str(n).strip())
    tf["KP_NAME"] = tf["TEAM"].apply(R)

    tf_h = tf[tf["VENUE"]=="Home"][["GAME-ID","KP_NAME","OEFF"]].copy()
    tf_r = tf[tf["VENUE"]=="Road"][["GAME-ID","KP_NAME","OEFF"]].copy()
    act = tf_h.merge(tf_r, on="GAME-ID", suffixes=("_h","_a"))
    act = act.dropna(subset=["OEFF_h","OEFF_a"])
    act["GAME_ID"] = act["GAME-ID"].astype(str).str.strip()
    log.info(f"Actual OEFF: {len(act)} H/R game pairs")

    # ── Pair baselines H+R, join actual OEFF ───────────────────────
    paired = bh.merge(br, on="GAME_ID", suffixes=("_h","_a"))
    log.info(f"Baseline pairs: {len(paired)} H/R games")
    paired = paired.merge(act[["GAME_ID","OEFF_h","OEFF_a"]], on="GAME_ID", how="inner")
    paired = paired.dropna(subset=["OEFF_h","OEFF_a","bff_eFG_h","bff_eFG_a"]).copy()
    paired = paired.sort_values("DATE").reset_index(drop=True)
    log.info(f"Final paired dataset: {len(paired)} games with FF + actual OEFF")

    if len(paired) < 200:
        log.error(f"Only {len(paired)} games — insufficient."); return

    # ── Z-score features ────────────────────────────────────────────
    ff_mu = {}; ff_sd = {}
    for stat in ["eFG","TOV","ORB","FTR"]:
        all_v = pd.concat([paired[f"bff_{stat}_h"], paired[f"bff_{stat}_a"]])
        ff_mu[stat] = all_v.mean(); ff_sd[stat] = all_v.std() + 1e-9

    def z(col, stat): return (paired[col] - ff_mu[stat]) / ff_sd[stat]

    # Recompute z-scores using defensive columns too
    for stat, dcol in [("def_eFG","def_eFG_allowed"),("def_TOV","def_TOV_forced"),
                       ("def_DRB","def_DRB_rate"),("def_FTR","def_FTR_allowed")]:
        all_v = pd.concat([paired[f"{dcol}_h"], paired[f"{dcol}_a"]])
        ff_mu[stat] = all_v.mean(); ff_sd[stat] = all_v.std() + 1e-9

    def zd(col, stat): return (paired[col] - ff_mu[stat]) / ff_sd[stat]

    # Home offense vs away defense (higher = better scoring environment for home)
    paired["Xh_eFG"] =  z("bff_eFG_h","eFG")  + zd("def_eFG_allowed_a","def_eFG")
    paired["Xh_TOV"] = -z("bff_TOV_h","TOV")  - zd("def_TOV_forced_a","def_TOV")
    paired["Xh_ORB"] =  z("bff_ORB_h","ORB")  - zd("def_DRB_rate_a","def_DRB")
    paired["Xh_FTR"] =  z("bff_FTR_h","FTR")  + zd("def_FTR_allowed_a","def_FTR")
    # Away offense vs home defense
    paired["Xa_eFG"] =  z("bff_eFG_a","eFG")  + zd("def_eFG_allowed_h","def_eFG")
    paired["Xa_TOV"] = -z("bff_TOV_a","TOV")  - zd("def_TOV_forced_h","def_TOV")
    paired["Xa_ORB"] =  z("bff_ORB_a","ORB")  - zd("def_DRB_rate_h","def_DRB")
    paired["Xa_FTR"] =  z("bff_FTR_a","FTR")  + zd("def_FTR_allowed_h","def_FTR")

    FEAT_H = ["Xh_eFG","Xh_TOV","Xh_ORB","Xh_FTR"]
    FEAT_A = ["Xa_eFG","Xa_TOV","Xa_ORB","Xa_FTR"]

    paired["y_h"] = paired["OEFF_h"] - paired["blend_OEFF_h"]
    paired["y_a"] = paired["OEFF_a"] - paired["blend_OEFF_a"]
    log.info(f"y_h: mean={paired['y_h'].mean():.3f} std={paired['y_h'].std():.3f}")
    log.info(f"y_a: mean={paired['y_a'].mean():.3f} std={paired['y_a'].std():.3f}")

    # ── OOF Ridge ──────────────────────────────────────────────────
    Xh = paired[FEAT_H].fillna(0).values
    Xa = paired[FEAT_A].fillna(0).values
    yh = paired["y_h"].values
    ya = paired["y_a"].values
    oof_dh = np.zeros(len(paired)); oof_da = np.zeros(len(paired))
    coefs_h = []
    tss = TimeSeriesSplit(n_splits=5)
    log.info("Running OOF Ridge(alpha=10)...")
    for tr, te in tss.split(Xh):
        if len(tr) < 50: continue
        mh = Ridge(alpha=10.0); mh.fit(Xh[tr], yh[tr])
        oof_dh[te] = mh.predict(Xh[te]); coefs_h.append(mh.coef_)
        ma = Ridge(alpha=10.0); ma.fit(Xa[tr], ya[tr])
        oof_da[te] = ma.predict(Xa[te])

    oof_dh = np.clip(oof_dh, -DELTA_CLIP, DELTA_CLIP)
    oof_da = np.clip(oof_da, -DELTA_CLIP, DELTA_CLIP)
    paired["delta_h_ff"] = oof_dh
    paired["delta_a_ff"] = oof_da

    r2_h   = r2_score(yh, oof_dh)
    mae_h  = mean_absolute_error(yh, oof_dh)
    mean_d = float(np.abs(oof_dh).mean())
    p95_d  = float(np.percentile(np.abs(oof_dh), 95))
    avg_c  = np.mean(coefs_h, axis=0) if coefs_h else np.zeros(4)
    log.info(f"Residual R²={r2_h:.4f}  MAE={mae_h:.3f}  mean|delta|={mean_d:.3f}  p95={p95_d:.3f}")

    # ── Join deltas back to predictions ────────────────────────────
    preds = pd.read_csv(args.pred, parse_dates=["DATE"])
    preds = preds[preds["VENUE"]=="H/R"].copy()
    preds["KP_h"] = preds["TEAM_h"].apply(R)
    preds["KP_a"] = preds["TEAM_a"].apply(R)
    preds["DATE_str"] = preds["DATE"].dt.strftime("%Y-%m-%d")

    # Get GAME_ID for each pred row via bh lookup on KP_h + date
    bh_lookup = bh[["GAME_ID","KP_NAME","DATE"]].copy()
    bh_lookup["DATE_str"] = bh_lookup["DATE"].dt.strftime("%Y-%m-%d")
    bh_lookup = bh_lookup.rename(columns={"KP_NAME":"KP_h"})

    # Join preds to bh_lookup to get GAME_ID
    p2 = preds.merge(bh_lookup[["GAME_ID","KP_h","DATE_str"]],
                     on=["KP_h","DATE_str"], how="left")
    # GAME_ID may be suffixed after merge — find it
    if "GAME_ID" not in p2.columns:
        gid_cols = [c for c in p2.columns if "GAME_ID" in c]
        if gid_cols: p2["GAME_ID"] = p2[gid_cols[0]]
        else: p2["GAME_ID"] = ""
    p2["GAME_ID"] = p2["GAME_ID"].astype(str).str.strip()

    delta_map = paired[["GAME_ID","delta_h_ff","delta_a_ff"]].copy()
    delta_map["GAME_ID"] = delta_map["GAME_ID"].astype(str).str.strip()

    p2 = p2.merge(delta_map, on="GAME_ID", how="left")
    p2["delta_h_ff"] = p2["delta_h_ff"].fillna(0.0)
    p2["delta_a_ff"] = p2["delta_a_ff"].fillna(0.0)

    pace = paired["blend_POSS_h"].mean() if "blend_POSS_h" in paired.columns else 67.5
    p2["fair_spread_ff"] = p2["fair_spread"] + \
        (p2["delta_h_ff"] - p2["delta_a_ff"]) * pace / 100.0
    p2["fair_total_ff"]  = p2["fair_total"] + \
        (p2["delta_h_ff"] + p2["delta_a_ff"]) * pace / 100.0

    sp_v = p2["mkt_spread"].notna()
    tt_v = p2["mkt_total"].notna()
    p2["p_cover_ff"] = p2["p_home_cover"].copy()
    p2["p_over_ff"]  = p2["p_over"].copy()
    p2.loc[sp_v,"p_cover_ff"] = _stats.norm.cdf(
        (p2.loc[sp_v,"fair_spread_ff"] - (-p2.loc[sp_v,"mkt_spread"])) / SIGMA_M)
    p2.loc[tt_v,"p_over_ff"]  = 1 - _stats.norm.cdf(
        (p2.loc[tt_v,"mkt_total"] - p2.loc[tt_v,"fair_total_ff"]) / SIGMA_T)
    p2["p_cover_ff"] = np.clip(p2["p_cover_ff"], 0.01, 0.99)
    p2["p_over_ff"]  = np.clip(p2["p_over_ff"],  0.01, 0.99)
    p2["home_covered"] = pd.to_numeric(p2["home_covered"], errors="coerce")
    p2["over"]         = pd.to_numeric(p2["over"],         errors="coerce")

    # ── Acceptance tests ────────────────────────────────────────────
    if "DATE" not in p2.columns:
        p2["DATE"] = preds["DATE"].values[:len(p2)] if len(preds)==len(p2) else pd.NaT
    ats_r_b, ats_c_b = oof_auc(p2["home_covered"].values, p2["p_home_cover"].values)
    ats_r_f, ats_c_f = oof_auc(p2["home_covered"].values, p2["p_cover_ff"].values)
    tot_r_b, tot_c_b = oof_auc(p2["over"].values, p2["p_over"].values)
    tot_r_f, tot_c_f = oof_auc(p2["over"].values, p2["p_over_ff"].values)

    d_ats = round(((ats_c_f or 0) - (ats_c_b or 0)), 4)
    d_tot = round(((tot_c_f or 0) - (tot_c_b or 0)), 4)

    bkt_b  = edge_buckets(p2, "fair_spread",    "home_covered")
    bkt_f  = edge_buckets(p2, "fair_spread_ff", "home_covered")
    tot_b  = tot_buckets( p2, "fair_total",     "over")
    tot_f  = tot_buckets( p2, "fair_total_ff",  "over")

    sign_ok = bool(avg_c[0]>0 and avg_c[1]<0 and avg_c[2]>0 and avg_c[3]>0)

    tests = [
        ("[1] OEFF R²>0",           r2_h > 0,
            f"R²={r2_h:.4f}", ">0"),
        ("[2] ΔATS_AUC>=+0.010",    d_ats >= 0.010,
            f"Δ={d_ats:+.4f}", ">=+0.010"),
        ("[3] ΔTOT_AUC>=-0.005",    d_tot >= -0.005,
            f"Δ={d_tot:+.4f}", ">=-0.005"),
        ("[4] ATS 3-5>=baseline",
            get_ev(bkt_f,"3-5") >= get_ev(bkt_b,"3-5"),
            f"{get_ev(bkt_f,'3-5'):.4f} vs {get_ev(bkt_b,'3-5'):.4f}", ">=baseline"),
        ("[5] ATS >5>=baseline",
            get_ev(bkt_f,">5") >= get_ev(bkt_b,">5"),
            f"{get_ev(bkt_f,'>5'):.4f} vs {get_ev(bkt_b,'>5'):.4f}", ">=baseline"),
        ("[6] TOT 2-4>=baseline",
            get_ev(tot_f,"2-4") >= get_ev(tot_b,"2-4"),
            f"{get_ev(tot_f,'2-4'):.4f} vs {get_ev(tot_b,'2-4'):.4f}", ">=baseline"),
        ("[7] mean|delta|<=1.5",    mean_d <= 1.5,
            f"{mean_d:.3f}", "<=1.5"),
        ("[8] p95|delta|<=3.0",     p95_d <= 3.0,
            f"{p95_d:.3f}", "<=3.0"),
        ("[9] Coef signs correct",  sign_ok,
            f"eFG={avg_c[0]:+.3f} TOV={avg_c[1]:+.3f} ORB={avg_c[2]:+.3f} FTR={avg_c[3]:+.3f}",
            "eFG+ TOV- ORB+ FTR+"),
    ]
    n_pass = sum(1 for _, p, _, _ in tests if p)

    log.info(f"\n{'='*65}")
    log.info("ACCEPTANCE TESTS")
    log.info(f"{'='*65}")
    for name, passed, value, crit in tests:
        log.info(f"  {'PASS' if passed else 'FAIL'}  {name:<32} {value:<40} [{crit}]")

    log.info(f"\n  {n_pass}/9 passed")
    log.info(f"\n  CALIBRATION:")
    log.info(f"  ATS  base_raw={ats_r_b:.4f} base_cal={ats_c_b:.4f}  ff_raw={ats_r_f:.4f} ff_cal={ats_c_f:.4f}  ΔAUC_cal={d_ats:+.4f}")
    log.info(f"  TOT  base_raw={tot_r_b:.4f} base_cal={tot_c_b:.4f}  ff_raw={tot_r_f:.4f} ff_cal={tot_c_f:.4f}  ΔAUC_cal={d_tot:+.4f}")

    log.info(f"\n  ATS EDGE BUCKETS (baseline → FF layer):")
    log.info(f"  {'Bucket':<10} {'Base EV':>9} {'Base N':>7}   {'FF EV':>9} {'FF N':>7}  {'Vig':>4}")
    for (_, rb), (_, rf) in zip(bkt_b.iterrows(), bkt_f.iterrows()):
        log.info(f"  {str(rb['bucket']):<10} {rb['ev']:>+9.4f} {rb['n']:>7}   "
                 f"{rf['ev']:>+9.4f} {rf['n']:>7}  {'✓' if rf['cr']>VIG_BE else ''}")

    if n_pass == 9:
        verdict = "ALL 9 PASS — FF layer PROMOTED to production"
    else:
        verdict = f"{9-n_pass} tests FAILED — FF layer EXPERIMENTAL. Production = team_only_v1_p2_30"
    log.info(f"\n  VERDICT: {verdict}")

    p2.to_csv(args.out, index=False)
    log.info(f"\nWritten: {args.out} ({len(p2)} games)")

if __name__ == "__main__":
    main()
