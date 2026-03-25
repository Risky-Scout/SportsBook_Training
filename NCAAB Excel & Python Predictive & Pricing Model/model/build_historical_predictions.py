from __future__ import annotations
"""
build_historical_predictions.py — Phase 3D True Walk-Forward Calibration (final)
All 7 prior fixes plus:
  Fix 1b: pmf_grid_sum consistent throughout (no grid_sum alias)
  Fix 2b: run_calibration returns OOF p_cal arrays; edge table uses calibrated
          probabilities when available, raw otherwise

EV@-110 = cover_rate*(100/110) - (1-cover_rate), breakeven = 52.381%
Calibration: TimeSeriesSplit(5), OOF indices only, never prefix zeros
Side-aware edge: bet home if fair_spread > -mkt_spread, else away
Neutral: sa=0, calibrated separately if n>=100
"""
import sys, math, argparse, logging, glob
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import special
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LinearRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import TimeSeriesSplit
from sklearn.calibration import calibration_curve

logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
log = logging.getLogger("phase3d")

PHI,SIG,NQ,MX          = 0.004,0.085,9,130
WO,WD                   = 0.55,0.45
LAM_OE,LAM_DE,LAM_TP   = 0.30,0.30,0.20
KP_LG_SYM,KP_LG_TP     = 109.29,67.39
BDB_LG_SYM,BDB_LG_TP   = 106.157,72.270
SA_HOME,SA_NEUTRAL      = 1.957,0.0
VIG_MULT                = 100.0/110.0
VIG_BREAKEVEN           = 1.0/(1.0+VIG_MULT)   # 52.381%

def ats_ev(cr): return cr*VIG_MULT-(1.0-cr)

import re as _re
XWALK={k:v for k,v in _re.findall(r'"([^"]{3,}?)"\s*:\s*"([^"]{2,}?)"',
    open("run_phase3a1_production.py").read()) if len(k)>4}
def R(n): return XWALK.get(str(n).strip(),str(n).strip())

# ── Exact PMF joint grid ──────────────────────────────────────────────────
def nb_lpmf(k,mu,phi):
    r=1.0/phi; p=r/(r+mu)
    return (special.gammaln(k+r)-special.gammaln(r)-special.gammaln(k+1)
            +r*np.log(max(p,1e-12))+k*np.log(max(1.0-p,1e-12)))

def price_exact(mp,h_ortg,a_ortg,mkt_spread=None,mkt_total=None):
    pts,wts=np.polynomial.hermite.hermgauss(NQ)
    lmu=math.log(max(mp,1.0))-0.5*SIG*SIG
    xs=np.arange(MX+1,dtype=float)
    g=np.zeros((MX+1,MX+1)); eh=ea=0.0
    for pt,wt in zip(pts,wts):
        pace=math.exp(lmu+math.sqrt(2.0)*SIG*pt); wg=wt/math.sqrt(math.pi)
        mh=max(pace*h_ortg/100.0,0.1); ma=max(pace*a_ortg/100.0,0.1)
        ph=np.exp(nb_lpmf(xs,mh,PHI)); ph/=ph.sum()
        pa=np.exp(nb_lpmf(xs,ma,PHI)); pa/=pa.sum()
        g+=wg*np.outer(ph,pa); eh+=wg*(xs*ph).sum(); ea+=wg*(xs*pa).sum()
    s=g.sum();
    if s>0: g/=s
    n=MX+1; mg=np.zeros(2*n-1); tg=np.zeros(2*n-1)
    mv=np.arange(-(n-1),n); tv=np.arange(2*n-1)
    for i in range(n):
        np.add.at(mg,i-np.arange(n)+(n-1),g[i]); np.add.at(tg,i+np.arange(n),g[i])
    p_ml   =float(mg[mv>0].sum())
    p_cover=float(mg[mv>-mkt_spread].sum()) if mkt_spread is not None else float("nan")
    p_over =float(tg[tv>mkt_total].sum())   if mkt_total  is not None else float("nan")
    return {"fair_spread":round(eh-ea,3),"fair_total":round(eh+ea,3),
            "p_ml_home":round(p_ml,4),"p_home_cover":round(p_cover,4),
            "p_over":round(p_over,4),"pmf_grid_sum":round(g.sum(),8)}

# ── KenPom archives — strict no-future fallback ───────────────────────────
def load_archives(kenpom_dir):
    archives={}
    for path in sorted(glob.glob(f"{kenpom_dir}/KenPom_Archive_*.csv")):
        ds=Path(path).stem.replace("KenPom_Archive_","")
        kp=pd.read_csv(path); kp["TeamName"]=kp["TeamName"].str.strip()
        archives[ds]=kp.set_index("TeamName")
    log.info(f"  KenPom archives: {len(archives)} — {sorted(archives)}")
    return archives

def get_kenpom(archives,game_date_str):
    """Strict: only snapshots strictly BEFORE game_date. No future fallback."""
    if not archives: return None,None
    target=pd.Timestamp(game_date_str)
    cands=[d for d in archives if pd.Timestamp(d)<=target]
    if not cands: return None,None
    best=sorted(cands)[-1]; return archives[best],best

# ── Score one game ────────────────────────────────────────────────────────
def score_game(row,archives,n_kp,n_bdb,sa):
    game_date=row["DATE"].strftime("%Y-%m-%d") if pd.notna(row["DATE"]) else "2026-01-01"
    bdb_oe_h=float(row["blend_OEFF_h"]); bdb_de_h=float(row["blend_DEFF_h"]); bdb_tp_h=float(row["blend_POSS_h"])
    bdb_oe_a=float(row["blend_OEFF_a"]); bdb_de_a=float(row["blend_DEFF_a"]); bdb_tp_a=float(row["blend_POSS_a"])
    h_kp=str(row["TEAM_h_kp"]); a_kp=str(row["TEAM_a_kp"])
    kp_snap,snap_date=get_kenpom(archives,game_date)
    if kp_snap is not None and h_kp in kp_snap.index and a_kp in kp_snap.index:
        kp_oe_h=float(kp_snap.loc[h_kp,"AdjOE"]); kp_de_h=float(kp_snap.loc[h_kp,"AdjDE"]); kp_tp_h=float(kp_snap.loc[h_kp,"AdjTempo"])
        kp_oe_a=float(kp_snap.loc[a_kp,"AdjOE"]); kp_de_a=float(kp_snap.loc[a_kp,"AdjDE"]); kp_tp_a=float(kp_snap.loc[a_kp,"AdjTempo"])
        kp_used=True; n_kp[0]+=1
    else:
        kp_oe_h=kp_de_h=kp_oe_a=kp_de_a=KP_LG_SYM; kp_tp_h=kp_tp_a=KP_LG_TP
        kp_used=False; snap_date=None; n_bdb[0]+=1
    oe_h=kp_oe_h+LAM_OE*(bdb_oe_h-BDB_LG_SYM); de_h=kp_de_h+LAM_DE*(bdb_de_h-BDB_LG_SYM); tp_h=kp_tp_h+LAM_TP*(bdb_tp_h-BDB_LG_TP)
    oe_a=kp_oe_a+LAM_OE*(bdb_oe_a-BDB_LG_SYM); de_a=kp_de_a+LAM_DE*(bdb_de_a-BDB_LG_SYM); tp_a=kp_tp_a+LAM_TP*(bdb_tp_a-BDB_LG_TP)
    blg=KP_LG_SYM; harm=2.0/(1.0/max(tp_h,50)+1.0/max(tp_a,50)); mp=0.85*harm+0.15*KP_LG_TP
    h_ortg=blg+WO*(oe_h-blg)+WD*(de_a-blg)+sa; a_ortg=blg+WO*(oe_a-blg)+WD*(de_h-blg)-sa
    mkt_sp=float(row["CLOSING_SPREAD"]) if pd.notna(row.get("CLOSING_SPREAD")) else None
    mkt_tt=float(row["CLOSING_TOTAL"])  if pd.notna(row.get("CLOSING_TOTAL"))  else None
    pmf=price_exact(mp,h_ortg,a_ortg,mkt_sp,mkt_tt)
    if abs(pmf["pmf_grid_sum"]-1.0)>1e-6: return None
    return {"DATE":game_date,"GAME_ID":row.get("GAME-ID",row.get("GAME_ID")),
            "VENUE":row.get("VENUE","H/R"),
            "TEAM_h":row["TEAM_h"],"TEAM_a":row["TEAM_a"],
            "TEAM_h_kp":h_kp,"TEAM_a_kp":a_kp,
            "games_played_h":int(row["games_played_h"]),"games_played_a":int(row["games_played_a"]),
            "kenpom_used":kp_used,"kenpom_snap_date":snap_date,
            "oe_h":round(oe_h,3),"de_h":round(de_h,3),"oe_a":round(oe_a,3),"de_a":round(de_a,3),
            "h_ortg":round(h_ortg,3),"a_ortg":round(a_ortg,3),"mu_pace":round(mp,3),"sa":sa,
            "fair_spread":pmf["fair_spread"],"fair_total":pmf["fair_total"],
            "p_ml_home":pmf["p_ml_home"],"p_home_cover":pmf["p_home_cover"],"p_over":pmf["p_over"],
            "pmf_grid_sum":pmf["pmf_grid_sum"],   # consistent name
            "mkt_spread":mkt_sp,"mkt_total":mkt_tt,
            "actual_margin":int(row["actual_margin"]),"actual_total":int(row["actual_total"]),
            "home_win":int(row["home_win"]),
            "home_covered":row.get("home_covered"),"over":row.get("over"),}

# ── Calibration: OOF only, returns calibrated p arrays ───────────────────
def run_calibration(preds_df, label):
    """
    Returns (cal_results_list, cal_preds_df).
    cal_preds_df is preds_df with added columns:
      p_ml_home_cal, p_home_cover_cal, p_over_cal
    Only OOF rows are calibrated; non-OOF rows carry raw value.
    cal_is_oof column flags which rows were in an OOF fold.
    """
    tss=TimeSeriesSplit(n_splits=5)
    results=[]
    df=preds_df.copy().reset_index(drop=True)
    df["p_ml_home_cal"]    = df["p_ml_home"]      # default = raw
    df["p_home_cover_cal"] = df["p_home_cover"]
    df["p_over_cal"]       = df["p_over"]
    df["cal_is_oof"]       = False

    for name,y_col,p_col,cal_col in [
        ("ML  (home win)", "home_win",    "p_ml_home",    "p_ml_home_cal"),
        ("ATS (h cover)",  "home_covered","p_home_cover", "p_home_cover_cal"),
        ("TOT (over)",     "over",        "p_over",       "p_over_cal"),
    ]:
        sub=df.dropna(subset=[y_col,p_col]).copy()
        sub=sub[sub[p_col].between(0.01,0.99)].sort_values("DATE").reset_index()
        # 'index' = original row index in df
        if len(sub)<100:
            log.warning(f"  {label} {name}: n={len(sub)}<100 — skip cal")
            continue
        yt=sub[y_col].values.astype(float); yp=sub[p_col].values
        orig_idx=sub["index"].values

        bs_raw=brier_score_loss(yt,yp); ll_raw=log_loss(yt,yp); auc_raw=roc_auc_score(yt,yp)
        naive=brier_score_loss(yt,np.full(len(yt),yt.mean())); bss_raw=1-bs_raw/naive
        n_bins=min(10,len(sub)//50)
        if n_bins>=3:
            pt,pp=calibration_curve(yt,yp,n_bins=n_bins)
            lr=LinearRegression().fit(pp.reshape(-1,1),pt)
            slope=float(lr.coef_[0]); intercept=float(lr.intercept_)
        else: slope=float("nan"); intercept=float("nan")

        # OOF accumulation
        oof_pos=[]; oof_cal=[]
        for tr,te in tss.split(yt):
            if len(tr)<20: continue
            iso=IsotonicRegression(out_of_bounds="clip")
            iso.fit(yp[tr],yt[tr]); oof_pos.extend(te.tolist()); oof_cal.extend(iso.predict(yp[te]).tolist())
        if not oof_pos: continue
        oof_pos=np.array(oof_pos); oof_cal=np.array(oof_cal)
        yt_oof=yt[oof_pos]; yp_oof=yp[oof_pos]

        bs_cal=brier_score_loss(yt_oof,oof_cal); ll_cal=log_loss(yt_oof,np.clip(oof_cal,1e-6,1-1e-6))
        auc_cal=roc_auc_score(yt_oof,oof_cal)
        naive_oof=brier_score_loss(yt_oof,np.full(len(yt_oof),yt_oof.mean())); bss_cal=1-bs_cal/naive_oof

        # Write calibrated probs back to df at OOF original indices
        for pos_i,cal_v in zip(oof_pos,oof_cal):
            df_idx=orig_idx[pos_i]
            df.at[df_idx,cal_col]=round(float(cal_v),4)
            df.at[df_idx,"cal_is_oof"]=True

        log.info(f"\n  {label} — {name}  (n_total={len(sub)} n_oof={len(oof_pos)}):")
        log.info(f"    Raw: Brier={bs_raw:.4f} BSS={bss_raw:+.4f} LogLoss={ll_raw:.4f} AUC={auc_raw:.4f}")
        log.info(f"    Cal: Brier={bs_cal:.4f} BSS={bss_cal:+.4f} LogLoss={ll_cal:.4f} AUC={auc_cal:.4f}")
        log.info(f"    Slope={slope:.3f} Intercept={intercept:.3f} ΔBrier={bs_cal-bs_raw:+.4f}")
        if auc_raw>0.75: log.warning(f"    AUC={auc_raw:.4f}>0.75 — possible leakage")

        results.append({"subset":label,"market_type":name,
            "n_total":len(sub),"n_oof":len(oof_pos),"outcome_rate":round(yt.mean(),4),
            "brier_raw":round(bs_raw,4),"brier_cal_oof":round(bs_cal,4),"brier_delta":round(bs_cal-bs_raw,4),
            "bss_raw":round(bss_raw,4),"bss_cal_oof":round(bss_cal,4),
            "logloss_raw":round(ll_raw,4),"logloss_cal_oof":round(ll_cal,4),
            "auc_raw":round(auc_raw,4),"auc_cal_oof":round(auc_cal,4),
            "cal_slope":round(slope,3) if not math.isnan(slope) else "n/a",
            "cal_intercept":round(intercept,3) if not math.isnan(intercept) else "n/a",
            "naive_brier":round(naive,4),"split_method":"TimeSeriesSplit(5) OOF only",
            "leakage_flag":"OK" if auc_raw<=0.75 else "WARN>0.75"})
    return results, df

# ── Side-aware edge table (calibrated probs when available) ───────────────
def build_edge_table(preds_df, label):
    """
    Fix 6+2b: Uses p_home_cover_cal (calibrated) when cal_is_oof=True,
    falls back to raw p_home_cover otherwise.
    chosen_side = home if edge>0, else away.
    """
    p=preds_df.dropna(subset=["mkt_spread","home_covered","p_home_cover"]).copy()
    p["home_covered"]=p["home_covered"].astype(float)
    p["edge"]=p["fair_spread"]-(-p["mkt_spread"])
    # Use calibrated prob where available, raw otherwise
    if "p_home_cover_cal" in p.columns:
        p["p_cover_use"]=np.where(p.get("cal_is_oof",False),p["p_home_cover_cal"],p["p_home_cover"])
    else:
        p["p_cover_use"]=p["p_home_cover"]
    p["bet_home"]     =p["edge"]>0
    p["chosen_cover"] =np.where(p["bet_home"],p["home_covered"],1.0-p["home_covered"])
    p["chosen_prob"]  =np.where(p["bet_home"],p["p_cover_use"],1.0-p["p_cover_use"])
    p["abs_edge"]     =p["edge"].abs()
    p["prob_source"]  =np.where(p.get("cal_is_oof",False),"calibrated","raw")

    bins=[0,1.5,3,5,99]; labels=["0-1.5(weak)","1.5-3","3-5",">5"]
    p["abs_bucket"]=pd.cut(p["abs_edge"],bins=bins,labels=labels)
    bkt=p.groupby("abs_bucket",observed=True).agg(
        n               =("chosen_cover","count"),
        chosen_cover_rate=("chosen_cover","mean"),
        chosen_prob_mean =("chosen_prob","mean"),
        mean_abs_edge    =("abs_edge","mean"),
        pct_bet_home     =("bet_home","mean"),
        n_cal_probs      =("prob_source",lambda x:(x=="calibrated").sum()),
    ).reset_index()
    bkt["vig_breakeven"]=round(VIG_BREAKEVEN,4)
    bkt["ev_at_110"]=bkt["chosen_cover_rate"].apply(lambda cr:round(ats_ev(cr),4))
    bkt["beats_vig"]=bkt["chosen_cover_rate"]>VIG_BREAKEVEN
    bkt["subset"]=label
    return bkt

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--baselines", default="cbb_cache/TeamBaselines.csv")
    ap.add_argument("--team-feed", default="feeds_daily/03-20-2026-cbb-season-team-feed.xlsx",dest="team_feed")
    ap.add_argument("--kenpom-dir",default="cbb_cache",dest="kenpom_dir")
    ap.add_argument("--out-pred",  default="cbb_cache/historical_p230_predictions.csv",dest="out_pred")
    ap.add_argument("--out-cal",   default="cbb_cache/model_calibration_report.csv",dest="out_cal")
    ap.add_argument("--out-edge",  default="cbb_cache/edge_bucket_table.csv",dest="out_edge")
    ap.add_argument("--min-games", type=int,default=10,dest="min_games")
    args=ap.parse_args()

    log.info("="*65); log.info("Phase 3D — Final Walk-Forward Calibration")
    log.info(f"  EV@-110 = cr*{VIG_MULT:.5f}-(1-cr)  breakeven={VIG_BREAKEVEN:.4%}")
    log.info("="*65)

    bas=pd.read_csv(args.baselines,parse_dates=["DATE"])
    log.info(f"TeamBaselines: {len(bas):,} rows {bas['DATE'].min().date()}→{bas['DATE'].max().date()}")
    bas["KP_NAME_resolved"]=bas["KP_NAME"].apply(R)
    bas_home=bas[bas["VENUE"]=="Home"].copy()
    bas_road=bas[bas["VENUE"]=="Road"].copy()
    bas_neut=bas[bas["VENUE"]=="Neutral"].copy()

    df=pd.read_excel(args.team_feed,engine="openpyxl")
    df.columns=[str(c).replace("\n"," ").strip() for c in df.columns]
    df["DATE"]=pd.to_datetime(df["DATE"],errors="coerce")
    for col in ["F","CLOSING SPREAD","CLOSING TOTAL"]:
        df[col]=pd.to_numeric(df[col],errors="coerce")

    archives=load_archives(args.kenpom_dir)
    n_kp=[0]; n_bdb=[0]

    # H/R pairs
    home_f=df[df["VENUE"]=="Home"][["GAME-ID","DATE","TEAM","F","CLOSING SPREAD","CLOSING TOTAL"]].copy()
    road_f=df[df["VENUE"]=="Road"][["GAME-ID","TEAM","F"]].copy()
    hr=home_f.merge(road_f,on="GAME-ID",suffixes=("_h","_a")).rename(
        columns={"TEAM":"TEAM_h","F":"F_h","TEAM_a":"TEAM_a","F_a":"F_a",
                 "CLOSING SPREAD":"CLOSING_SPREAD","CLOSING TOTAL":"CLOSING_TOTAL"})
    hr=hr.dropna(subset=["F_h","F_a"]).copy()
    hr["TEAM_h_kp"]=hr["TEAM_h"].apply(R); hr["TEAM_a_kp"]=hr["TEAM_a"].apply(R)
    hr["actual_margin"]=hr["F_h"]-hr["F_a"]; hr["actual_total"]=hr["F_h"]+hr["F_a"]
    hr["home_win"]=(hr["actual_margin"]>0).astype(int)
    hr["home_covered"]=np.where(hr["CLOSING_SPREAD"].notna(),
        ((hr["actual_margin"]+hr["CLOSING_SPREAD"])>0).astype(int),np.nan)
    hr["over"]=np.where(hr["CLOSING_TOTAL"].notna(),
        (hr["actual_total"]>hr["CLOSING_TOTAL"]).astype(int),np.nan)
    hr["VENUE"]="H/R"

    pred_hr=(hr.merge(bas_home[["GAME_ID","blend_OEFF","blend_DEFF","blend_POSS","games_played"]],
                      left_on=["GAME-ID"],right_on=["GAME_ID"],how="inner")
               .merge(bas_road[["GAME_ID","blend_OEFF","blend_DEFF","blend_POSS","games_played"]],
                      left_on=["GAME-ID"],right_on=["GAME_ID"],how="inner",
                      suffixes=("_h","_a")))
    pred_hr=pred_hr[(pred_hr["games_played_h"]>=args.min_games)&
                    (pred_hr["games_played_a"]>=args.min_games)].copy()
    log.info(f"H/R joined+filtered: {len(pred_hr)}")

    hr_rows=[]; batch=max(1,len(pred_hr)//10)
    for i,(_,row) in enumerate(pred_hr.iterrows()):
        if i%batch==0: log.info(f"  H/R {i}/{len(pred_hr)}...")
        out=score_game(row,archives,n_kp,n_bdb,SA_HOME)
        if out: hr_rows.append(out)
    preds_hr=pd.DataFrame(hr_rows)
    log.info(f"H/R scored: {len(preds_hr)}")

    # Neutral pairs
    neut_rows_out=[]; n_neut=0
    if len(bas_neut)>0:
        neut_f=df[df["VENUE"]=="Neutral"].copy()
        for game_id,grp in neut_f.groupby("GAME-ID"):
            if len(grp)!=2: continue
            grp=grp.sort_values("TEAM").reset_index(drop=True)
            t1=grp.iloc[0]; t2=grp.iloc[1]
            t1_kp=R(t1["TEAM"]); t2_kp=R(t2["TEAM"])
            t1b=bas_neut[(bas_neut["KP_NAME_resolved"]==t1_kp)&(bas_neut["GAME_ID"]==game_id)]
            t2b=bas_neut[(bas_neut["KP_NAME_resolved"]==t2_kp)&(bas_neut["GAME_ID"]==game_id)]
            if len(t1b)==0 or len(t2b)==0: continue
            t1b=t1b.iloc[0]; t2b=t2b.iloc[0]
            if (pd.isna(t1b["blend_OEFF"]) or pd.isna(t2b["blend_OEFF"]) or
                int(t1b["games_played"])<args.min_games or int(t2b["games_played"])<args.min_games): continue
            mkt_sp=pd.to_numeric(t1.get("CLOSING SPREAD"),errors="coerce")
            mkt_tt=pd.to_numeric(t1.get("CLOSING TOTAL"), errors="coerce")
            am=int(t1["F"])-int(t2["F"]); at=int(t1["F"])+int(t2["F"])
            merged=pd.Series({"GAME-ID":game_id,"DATE":t1["DATE"],
                "TEAM_h":t1["TEAM"],"TEAM_a":t2["TEAM"],"TEAM_h_kp":t1_kp,"TEAM_a_kp":t2_kp,
                "blend_OEFF_h":t1b["blend_OEFF"],"blend_DEFF_h":t1b["blend_DEFF"],"blend_POSS_h":t1b["blend_POSS"],
                "blend_OEFF_a":t2b["blend_OEFF"],"blend_DEFF_a":t2b["blend_DEFF"],"blend_POSS_a":t2b["blend_POSS"],
                "games_played_h":int(t1b["games_played"]),"games_played_a":int(t2b["games_played"]),
                "actual_margin":am,"actual_total":at,"home_win":int(am>0),
                "CLOSING_SPREAD":mkt_sp,"CLOSING_TOTAL":mkt_tt,"VENUE":"Neutral",
                "home_covered":(float(am+mkt_sp)>0 if pd.notna(mkt_sp) else np.nan),
                "over":(float(at)>float(mkt_tt) if pd.notna(mkt_tt) else np.nan)})
            out=score_game(merged,archives,n_kp,n_bdb,SA_NEUTRAL)
            if out: out["VENUE"]="Neutral"; neut_rows_out.append(out); n_neut+=1
    preds_neut=pd.DataFrame(neut_rows_out) if neut_rows_out else pd.DataFrame()
    log.info(f"Neutral scored: {n_neut}")

    all_preds=pd.concat([preds_hr,preds_neut],ignore_index=True)
    all_preds["DATE"]=pd.to_datetime(all_preds["DATE"])
    all_preds=all_preds.sort_values("DATE").reset_index(drop=True)
    all_preds.to_csv(args.out_pred,index=False)
    log.info(f"Written: {args.out_pred} ({len(all_preds)} games)")
    log.info(f"  H/R:{len(preds_hr)} Neutral:{len(preds_neut)} KP:{n_kp[0]} BDB:{n_bdb[0]}")

    # Calibration
    log.info("\nRunning calibration (OOF only)...")
    preds_hr_s=preds_hr.sort_values("DATE").reset_index(drop=True)
    cal_hr,preds_hr_cal=run_calibration(preds_hr_s,"H/R")
    cal_neut=[]; preds_neut_cal=preds_neut.copy()
    if len(preds_neut)>=100:
        preds_neut_s=preds_neut.sort_values("DATE").reset_index(drop=True)
        cal_neut,preds_neut_cal=run_calibration(preds_neut_s,"Neutral")
    else:
        log.warning(f"  Neutral n={len(preds_neut)}<100 — no calibration; raw probs only")
        if len(preds_neut)>0:
            preds_neut_cal["p_home_cover_cal"]=preds_neut_cal["p_home_cover"]
            preds_neut_cal["cal_is_oof"]=False

    cal_df=pd.DataFrame(cal_hr+cal_neut)
    cal_df.to_csv(args.out_cal,index=False)
    log.info(f"Written: {args.out_cal}")

    # Edge tables (calibrated probs where OOF)
    log.info("\nBuilding side-aware edge tables (calibrated probs where available)...")
    edge_tbls=[build_edge_table(preds_hr_cal,"H/R")]
    if len(preds_neut_cal)>=50: edge_tbls.append(build_edge_table(preds_neut_cal,"Neutral"))
    edge_df=pd.concat(edge_tbls,ignore_index=True)
    edge_df.to_csv(args.out_edge,index=False)
    log.info(f"Written: {args.out_edge}")

    # Verification
    log.info(f"\n{'='*65}\nPHASE 3D VERIFICATION\n{'='*65}")
    log.info(f"  Total games scored:      {len(all_preds)}")
    log.info(f"  H/R:                     {len(preds_hr)}")
    log.info(f"  Neutral:                 {len(preds_neut)}")
    log.info(f"  KenPom-at-date:          {n_kp[0]} ({100*n_kp[0]/max(len(all_preds),1):.1f}%)")
    log.info(f"  BDB-only fallback:       {n_bdb[0]} ({100*n_bdb[0]/max(len(all_preds),1):.1f}%)")
    log.info(f"  pmf_grid_sum errors:     {((all_preds['pmf_grid_sum']-1).abs()>1e-6).sum()}")
    if len(cal_df)>0:
        log.info(f"\n  CALIBRATION (OOF, TimeSeriesSplit — edge table uses cal probs):")
        log.info(f"  {'Sub':<8} {'Market':<20} {'N_oof':>6} {'AUC_raw':>8} {'AUC_cal':>8} "
                 f"{'B_raw':>7} {'B_cal':>7} {'ΔB':>6} {'Slope':>6} {'Flag':>6}")
        for _,r in cal_df.iterrows():
            log.info(f"  {str(r['subset']):<8} {str(r['market_type']):<20} {r['n_oof']:>6} "
                     f"{r['auc_raw']:>8.4f} {r['auc_cal_oof']:>8.4f} "
                     f"{r['brier_raw']:>7.4f} {r['brier_cal_oof']:>7.4f} "
                     f"{r['brier_delta']:>+6.4f} {str(r['cal_slope']):>6} "
                     f"{str(r.get('leakage_flag','OK')):>6}")
    log.info(f"\n  SIDE-AWARE EDGE (chosen side=home if edge>0 else away, cal probs where OOF):")
    log.info(f"  Breakeven={VIG_BREAKEVEN:.4%}  EV=cr*{VIG_MULT:.5f}-(1-cr)")
    log.info(f"  {'Sub':<8} {'Bucket':<12} {'N':>5} {'CovR':>7} {'CalP':>7} "
             f"{'MeanE':>7} {'EV':>8} {'Vig':>5} {'NCal':>5}")
    for _,r in edge_df.iterrows():
        flag="  ✓" if r["beats_vig"] else ""
        log.info(f"  {str(r['subset']):<8} {str(r['abs_bucket']):<12} {r['n']:>5} "
                 f"{r['chosen_cover_rate']:>7.3f} {r['chosen_prob_mean']:>7.3f} "
                 f"{r['mean_abs_edge']:>7.2f} {r['ev_at_110']:>8.4f} {flag} {int(r['n_cal_probs']):>5}")
    log.info(f"\n  AUC guide: 0.52-0.55 weak, 0.55-0.65 useful, >0.75 check leakage")
    log.info(f"  'Beats vig' only meaningful n>=100, AUC not flagged")

if __name__=="__main__": main()
