"""
build_ff_residual_layer.py  —  Phase 2: Four-Factor Residual Layer v2
======================================================================
Offensive FF: TeamBaselines blend_g_* (historically blended, leakage-safe)
Defensive FF: KenPom FF archive DeFG_Pct, DTO_Pct, DOR_Pct, DFT_Rate
              (opponent-adjusted, correct directional meaning)

For historical games: uses nearest available KenPom FF archive
For present-day: uses today's FF archive

Matchup features (higher = better scoring environment for that offense):
  Xh_eFG =  z(blend_g_eFG_h)  + z(DeFG_Pct_a)   [away eFG allowed = weak defense]
  Xh_TOV = -z(blend_g_TOV_h)  - z(DTO_Pct_a)    [away forces fewer TOV = weak def]
  Xh_ORB =  z(blend_g_ORB_h)  - z(DOR_Pct_a)    [away grabs fewer def reb = weak]
  Xh_FTR =  z(blend_g_FTR_h)  + z(DFT_Rate_a)   [away gives more FT = weak def]
  (mirror for away)

Targets:
  y_h = actual_home_OEFF - h_ortg_base
  y_a = actual_away_OEFF - a_ortg_base

Model: Ridge(alpha=10), TimeSeriesSplit(5), OOF, chronological
Clip: ±2.5 pts/100 possessions
"""
from __future__ import annotations
import argparse, logging, re, glob, os
import numpy as np
import pandas as pd
from scipy import stats as _stats
from sklearn.linear_model import Ridge
from sklearn.metrics import r2_score, mean_absolute_error, roc_auc_score
from sklearn.model_selection import TimeSeriesSplit
from sklearn.isotonic import IsotonicRegression

logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
log = logging.getLogger("ff_residual")

VIG_MULT = 100.0/110.0
VIG_BE   = 1.0/(1.0+VIG_MULT)
DELTA_CLIP = 2.5
SIGMA_M    = 11.0
SIGMA_T    = 18.0

def ats_ev(cr): return round(cr*VIG_MULT-(1-cr), 4)

def oof_auc(y, p):
    y=np.array(y,dtype=float); p=np.array(p,dtype=float)
    mask=np.isfinite(y)&np.isfinite(p)
    y,p=y[mask],p[mask]
    if len(y)<100 or y.mean() in (0.,1.): return float("nan"),float("nan")
    auc_r=roc_auc_score(y,p)
    tss=TimeSeriesSplit(5); oof_p=np.full(len(y),np.nan)
    for tr,te in tss.split(y):
        if len(tr)<30: continue
        iso=IsotonicRegression(out_of_bounds="clip")
        iso.fit(p[tr],y[tr]); oof_p[te]=iso.predict(p[te])
    valid=np.isfinite(oof_p)
    auc_c=roc_auc_score(y[valid],oof_p[valid]) if valid.sum()>50 else float("nan")
    return round(auc_r,4),round(auc_c,4)

def edge_buckets(df,sp_col,cov_col):
    p=df.dropna(subset=[sp_col,"mkt_spread",cov_col]).copy()
    p[cov_col]=p[cov_col].astype(float)
    p["edge"]=p[sp_col]-(-p["mkt_spread"])
    p["chosen"]=np.where(p["edge"]>0,p[cov_col],1-p[cov_col])
    p["abs_edge"]=p["edge"].abs()
    p["bucket"]=pd.cut(p["abs_edge"],bins=[0,1.5,3,5,99],labels=["0-1.5","1.5-3","3-5",">5"])
    bkt=p.groupby("bucket",observed=True).agg(n=("chosen","count"),cr=("chosen","mean")).reset_index()
    bkt["ev"]=bkt["cr"].apply(ats_ev)
    return bkt

def get_ev(bkt,bucket):
    row=bkt[bkt["bucket"]==bucket]
    return float(row["ev"].iloc[0]) if len(row) else float("nan")

def load_ff_archives(kp_dir):
    """Load all KenPom FF archives. Returns dict date_str -> DataFrame indexed by TeamName."""
    archives = {}
    for f in sorted(glob.glob(os.path.join(kp_dir, "KenPom_FF_Archive_*.csv"))):
        date_str = os.path.basename(f).replace("KenPom_FF_Archive_","").replace(".csv","")
        try:
            df = pd.read_csv(f).set_index("TeamName")
            archives[date_str] = df
        except Exception:
            pass
    return archives

def get_ff_for_date(archives, game_date_str):
    """Return FF snapshot for nearest date <= game_date."""
    if not archives: return None, None
    cands = [d for d in sorted(archives.keys()) if d <= game_date_str]
    if not cands: cands = sorted(archives.keys())[:1]  # use earliest if no prior
    best = cands[-1]
    return archives[best], best

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--baselines",  default="cbb_cache/TeamBaselines.csv")
    ap.add_argument("--pred",       default="cbb_cache/historical_p230_predictions.csv")
    ap.add_argument("--team-feed",  default="feeds_daily/03-22-2026-cbb-season-team-feed.xlsx",dest="team_feed")
    ap.add_argument("--kp-dir",     default="cbb_cache", dest="kp_dir")
    ap.add_argument("--out",        default="cbb_cache/ff_residual_predictions.csv")
    args=ap.parse_args()

    log.info("="*65)
    log.info("Four-Factor Residual Layer v2 (KenPom defensive FF)")
    log.info("="*65)

    # Load KenPom FF archives
    ff_archives = load_ff_archives(args.kp_dir)
    log.info(f"KenPom FF archives loaded: {len(ff_archives)} snapshots — {sorted(ff_archives.keys())}")
    if not ff_archives:
        log.error("No KenPom FF archives found. Run fetch_kenpom.py --date today first."); return

    # Load TeamBaselines
    bas=pd.read_csv(args.baselines,parse_dates=["DATE"])
    bas["GAME_ID"]=bas["GAME_ID"].astype(str).str.strip()
    log.info(f"TeamBaselines: {len(bas)} rows, {bas['KP_NAME'].nunique()} teams")

    bh=bas[bas["VENUE"]=="Home"][["GAME_ID","KP_NAME","DATE",
        "blend_g_eFG","blend_g_TOV","blend_g_ORB","blend_g_FTR",
        "blend_OEFF","blend_DEFF","blend_POSS"]].copy()
    br=bas[bas["VENUE"]=="Road"][["GAME_ID","KP_NAME",
        "blend_g_eFG","blend_g_TOV","blend_g_ORB","blend_g_FTR",
        "blend_OEFF","blend_DEFF","blend_POSS"]].copy()

    # Load actual OEFF
    log.info(f"Loading team feed: {args.team_feed}")
    tf=pd.read_excel(args.team_feed,engine="openpyxl")
    tf.columns=[str(c).replace("\n"," ").strip() for c in tf.columns]
    tf["DATE"]=pd.to_datetime(tf["DATE"],errors="coerce")
    tf["GAME-ID"]=tf["GAME-ID"].astype(str).str.strip()
    tf["OEFF"]=pd.to_numeric(tf["OEFF"],errors="coerce")

    src=open("run_phase3a1_production.py").read()
    entries=re.findall(r'"([^"]{3,}?)"\s*:\s*"([^"]{2,}?)"',src)
    xwalk={k:v for k,v in entries if len(k)>4}
    def R(n): return xwalk.get(str(n).strip(),str(n).strip())
    tf["KP_NAME"]=tf["TEAM"].apply(R)

    tf_h=tf[tf["VENUE"]=="Home"][["GAME-ID","KP_NAME","OEFF"]].copy()
    tf_r=tf[tf["VENUE"]=="Road"][["GAME-ID","KP_NAME","OEFF"]].copy()
    act=tf_h.merge(tf_r,on="GAME-ID",suffixes=("_h","_a")).dropna(subset=["OEFF_h","OEFF_a"])
    act["GAME_ID"]=act["GAME-ID"].astype(str).str.strip()
    log.info(f"Actual OEFF: {len(act)} H/R game pairs")

    # Pair baselines
    paired=bh.merge(br,on="GAME_ID",suffixes=("_h","_a"))
    paired=paired.merge(act[["GAME_ID","OEFF_h","OEFF_a"]],on="GAME_ID",how="inner")
    paired=paired.dropna(subset=["OEFF_h","OEFF_a","blend_g_eFG_h","blend_g_eFG_a"]).copy()
    paired=paired.sort_values("DATE").reset_index(drop=True)
    log.info(f"Paired dataset: {len(paired)} games")

    if len(paired)<200:
        log.error(f"Only {len(paired)} games — insufficient."); return

    # For each game, look up KenPom defensive FF for both teams
    log.info("Looking up KenPom defensive FF per game...")
    def_cols=["DeFG_Pct","DTO_Pct","DOR_Pct","DFT_Rate"]
    for col in def_cols:
        paired[f"{col}_h"]=np.nan
        paired[f"{col}_a"]=np.nan

    for i,row in paired.iterrows():
        game_date=row["DATE"].strftime("%Y-%m-%d")
        ff_snap,snap_date=get_ff_for_date(ff_archives,game_date)
        if ff_snap is None: continue
        h_kp=row["KP_NAME_h"]; a_kp=row["KP_NAME_a"]
        for col in def_cols:
            if col in ff_snap.columns:
                if h_kp in ff_snap.index:
                    paired.at[i,f"{col}_h"]=float(ff_snap.loc[h_kp,col])
                if a_kp in ff_snap.index:
                    paired.at[i,f"{col}_a"]=float(ff_snap.loc[a_kp,col])

    # Fill missing with column means
    for col in def_cols:
        for sfx in ["_h","_a"]:
            paired[f"{col}{sfx}"]=paired[f"{col}{sfx}"].fillna(paired[f"{col}{sfx}"].mean())

    coverage=paired["DeFG_Pct_h"].notna().mean()
    log.info(f"KenPom defensive FF coverage: {coverage:.1%}")

    # Z-score normalization
    def make_z(series_list):
        all_v=pd.concat(series_list)
        mu=all_v.mean(); sd=all_v.std()+1e-9
        return mu,sd

    off_stats={c:make_z([paired[f"blend_g_{c}_h"],paired[f"blend_g_{c}_a"]])
               for c in ["eFG","TOV","ORB","FTR"]}
    def_stats={c:make_z([paired[f"{c}_h"],paired[f"{c}_a"]])
               for c in def_cols}

    def zo(col,stat):
        mu,sd=off_stats[stat]; return (paired[col]-mu)/sd
    def zd(col,stat):
        mu,sd=def_stats[stat]; return (paired[col]-mu)/sd

    # Matchup features — higher = better for that offense
    # Defensive: DeFG_Pct high = allows high eFG = weak defense = good for offense
    # DTO_Pct high = forces many TO = bad for offense → negate
    # DOR_Pct high = grabs many def rebounds = bad for offense ORB → negate
    # DFT_Rate high = gives many FT = weak defense = good for offense
    paired["Xh_eFG"] =  zo("blend_g_eFG_h","eFG") + zd("DeFG_Pct_a","DeFG_Pct")
    paired["Xh_TOV"] = -zo("blend_g_TOV_h","TOV") - zd("DTO_Pct_a","DTO_Pct")
    paired["Xh_ORB"] =  zo("blend_g_ORB_h","ORB") - zd("DOR_Pct_a","DOR_Pct")
    paired["Xh_FTR"] =  zo("blend_g_FTR_h","FTR") + zd("DFT_Rate_a","DFT_Rate")
    paired["Xa_eFG"] =  zo("blend_g_eFG_a","eFG") + zd("DeFG_Pct_h","DeFG_Pct")
    paired["Xa_TOV"] = -zo("blend_g_TOV_a","TOV") - zd("DTO_Pct_h","DTO_Pct")
    paired["Xa_ORB"] =  zo("blend_g_ORB_a","ORB") - zd("DOR_Pct_h","DOR_Pct")
    paired["Xa_FTR"] =  zo("blend_g_FTR_a","FTR") + zd("DFT_Rate_h","DFT_Rate")

    FEAT_H=["Xh_eFG","Xh_TOV","Xh_ORB","Xh_FTR"]
    FEAT_A=["Xa_eFG","Xa_TOV","Xa_ORB","Xa_FTR"]

    # Targets
    paired["y_h"]=paired["OEFF_h"]-paired["blend_OEFF_h"]
    paired["y_a"]=paired["OEFF_a"]-paired["blend_OEFF_a"]
    log.info(f"y_h mean={paired['y_h'].mean():.3f} std={paired['y_h'].std():.3f}")
    log.info(f"y_a mean={paired['y_a'].mean():.3f} std={paired['y_a'].std():.3f}")

    # OOF Ridge
    Xh=paired[FEAT_H].fillna(0).values
    Xa=paired[FEAT_A].fillna(0).values
    yh=paired["y_h"].values; ya=paired["y_a"].values
    oof_dh=np.zeros(len(paired)); oof_da=np.zeros(len(paired))
    coefs_h=[]; tss=TimeSeriesSplit(5)
    log.info("Running OOF Ridge(alpha=10)...")
    for tr,te in tss.split(Xh):
        if len(tr)<50: continue
        mh=Ridge(alpha=10.0); mh.fit(Xh[tr],yh[tr])
        oof_dh[te]=mh.predict(Xh[te]); coefs_h.append(mh.coef_)
        ma=Ridge(alpha=10.0); ma.fit(Xa[tr],ya[tr])
        oof_da[te]=ma.predict(Xa[te])

    oof_dh=np.clip(oof_dh,-DELTA_CLIP,DELTA_CLIP)
    oof_da=np.clip(oof_da,-DELTA_CLIP,DELTA_CLIP)
    paired["delta_h_ff"]=oof_dh; paired["delta_a_ff"]=oof_da

    r2_h=r2_score(yh,oof_dh)
    mae_h=mean_absolute_error(yh,oof_dh)
    mean_d=float(np.abs(oof_dh).mean())
    p95_d=float(np.percentile(np.abs(oof_dh),95))
    avg_c=np.mean(coefs_h,axis=0) if coefs_h else np.zeros(4)
    log.info(f"R²={r2_h:.4f}  MAE={mae_h:.3f}  mean|delta|={mean_d:.3f}  p95={p95_d:.3f}")
    log.info(f"Coefs: eFG={avg_c[0]:+.4f} TOV={avg_c[1]:+.4f} ORB={avg_c[2]:+.4f} FTR={avg_c[3]:+.4f}")

    # Join back to predictions
    preds=pd.read_csv(args.pred,parse_dates=["DATE"])
    preds=preds[preds["VENUE"]=="H/R"].copy()
    preds["KP_h"]=preds["TEAM_h"].apply(R)
    preds["DATE_str"]=preds["DATE"].dt.strftime("%Y-%m-%d")
    preds["home_covered"]=pd.to_numeric(preds["home_covered"],errors="coerce")
    preds["over"]=pd.to_numeric(preds["over"],errors="coerce")

    bh_lookup=bh[["GAME_ID","KP_NAME","DATE"]].copy()
    bh_lookup["DATE_str"]=bh_lookup["DATE"].dt.strftime("%Y-%m-%d")
    bh_lookup["GAME_ID"]=bh_lookup["GAME_ID"].astype(str).str.strip()
    bh_lookup=bh_lookup.rename(columns={"KP_NAME":"KP_h"})

    p2=preds.merge(bh_lookup[["GAME_ID","KP_h","DATE_str"]],on=["KP_h","DATE_str"],how="left")
    if "GAME_ID" not in p2.columns:
        gc=[c for c in p2.columns if "GAME_ID" in c]
        p2["GAME_ID"]=p2[gc[0]] if gc else ""
    p2["GAME_ID"]=p2["GAME_ID"].astype(str).str.strip()

    delta_map=paired[["GAME_ID","delta_h_ff","delta_a_ff"]].copy()
    delta_map["GAME_ID"]=delta_map["GAME_ID"].astype(str).str.strip()
    p2=p2.merge(delta_map,on="GAME_ID",how="left")
    p2["delta_h_ff"]=p2["delta_h_ff"].fillna(0.0)
    p2["delta_a_ff"]=p2["delta_a_ff"].fillna(0.0)
    p2=p2.sort_values("DATE").reset_index(drop=True)

    pace=paired["blend_POSS_h"].mean() if "blend_POSS_h" in paired.columns else 67.5
    p2["fair_spread_ff"]=p2["fair_spread"]+(p2["delta_h_ff"]-p2["delta_a_ff"])*pace/100.0
    p2["fair_total_ff"] =p2["fair_total"] +(p2["delta_h_ff"]+p2["delta_a_ff"])*pace/100.0

    sp_v=p2["mkt_spread"].notna(); tt_v=p2["mkt_total"].notna()
    p2["p_cover_ff"]=p2["p_home_cover"].copy(); p2["p_over_ff"]=p2["p_over"].copy()
    p2.loc[sp_v,"p_cover_ff"]=_stats.norm.cdf(
        (p2.loc[sp_v,"fair_spread_ff"]-(-p2.loc[sp_v,"mkt_spread"]))/SIGMA_M)
    p2.loc[tt_v,"p_over_ff"]=1-_stats.norm.cdf(
        (p2.loc[tt_v,"mkt_total"]-p2.loc[tt_v,"fair_total_ff"])/SIGMA_T)
    p2["p_cover_ff"]=np.clip(p2["p_cover_ff"],0.01,0.99)
    p2["p_over_ff"]=np.clip(p2["p_over_ff"],0.01,0.99)

    # Acceptance tests
    ats_r_b,ats_c_b=oof_auc(p2["home_covered"].values,p2["p_home_cover"].values)
    ats_r_f,ats_c_f=oof_auc(p2["home_covered"].values,p2["p_cover_ff"].values)
    d_ats=round((ats_c_f or 0)-(ats_c_b or 0),4)

    bkt_b=edge_buckets(p2,"fair_spread","home_covered")
    bkt_f=edge_buckets(p2,"fair_spread_ff","home_covered")

    tests=[
        ("[1]  OEFF R²>0",           r2_h>0,
            f"R²={r2_h:.4f}",">0"),
        ("[2]  ΔATS_AUC>=+0.010",    d_ats>=0.010,
            f"Δ={d_ats:+.4f}",">=+0.010"),
        ("[3]  ATS 3-5>=baseline",
            get_ev(bkt_f,"3-5")>=get_ev(bkt_b,"3-5"),
            f"{get_ev(bkt_f,'3-5'):.4f} vs {get_ev(bkt_b,'3-5'):.4f}",">=baseline"),
        ("[4]  ATS >5>=base-0.010",
            get_ev(bkt_f,">5")>=get_ev(bkt_b,">5")-0.010,
            f"{get_ev(bkt_f,'>5'):.4f} vs {get_ev(bkt_b,'>5'):.4f}",">=base-0.010"),
        ("[5]  mean|delta|<=1.5",     mean_d<=1.5,
            f"{mean_d:.3f}","<=1.5"),
        ("[6]  eFG coef>0",           avg_c[0]>0,
            f"{avg_c[0]:+.4f}",">0"),
        ("[7]  TOV coef<0",           avg_c[1]<0,
            f"{avg_c[1]:+.4f}","<0"),
        ("[8]  ORB coef>0",           avg_c[2]>0,
            f"{avg_c[2]:+.4f}",">0"),
        ("[9]  FTR coef>0",           avg_c[3]>0,
            f"{avg_c[3]:+.4f}",">0"),
        ("[10] p95|delta|<=2.5",      p95_d<=2.5,
            f"{p95_d:.3f}","<=2.5"),
    ]
    n_pass=sum(1 for _,p,_,_ in tests if p)

    log.info(f"\n{'='*65}")
    log.info("ACCEPTANCE TESTS")
    log.info(f"{'='*65}")
    for name,passed,value,crit in tests:
        log.info(f"  {'PASS' if passed else 'FAIL'}  {name:<28} {value:<35} [{crit}]")
    log.info(f"\n  {n_pass}/10 passed")
    log.info(f"  AUC: base_raw={ats_r_b:.4f} base_cal={ats_c_b:.4f} "
             f"ff_raw={ats_r_f:.4f} ff_cal={ats_c_f:.4f} Δ={d_ats:+.4f}")
    log.info(f"\n  ATS BUCKETS:")
    log.info(f"  {'Bucket':<10} {'Base EV':>9} {'Base N':>7}   {'FF EV':>9} {'FF N':>7}")
    for (_,rb),(_,rf) in zip(bkt_b.iterrows(),bkt_f.iterrows()):
        log.info(f"  {str(rb['bucket']):<10} {rb['ev']:>+9.4f} {rb['n']:>7}   "
                 f"{rf['ev']:>+9.4f} {rf['n']:>7}  {'✓' if rf['cr']>VIG_BE else ''}")

    if n_pass>=8:
        verdict="PROMOTED to production"
    else:
        verdict=f"{10-n_pass} tests FAILED — EXPERIMENTAL. Production=team_only_v1_p2_30"
    log.info(f"\n  VERDICT: {verdict}")
    log.info(f"  NOTE: Only {len(ff_archives)} FF archive(s) available. "
             f"As daily archives accumulate, re-run for improved date-matched validation.")

    p2.to_csv(args.out,index=False)
    log.info(f"\nWritten: {args.out} ({len(p2)} games)")

if __name__=="__main__":
    main()
