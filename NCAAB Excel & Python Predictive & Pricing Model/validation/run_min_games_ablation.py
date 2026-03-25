
import subprocess, sys, argparse, os, tempfile
import pandas as pd
import numpy as np
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression as PlattLR
from sklearn.model_selection import TimeSeriesSplit

VIG_MULT = 100.0/110.0
VIG_BE   = 1.0/(1.0+VIG_MULT)
def ats_ev(cr): return cr*VIG_MULT-(1.0-cr)

def oof_metrics(df, y_col, p_col, use_platt=False):
    sub = df.dropna(subset=[y_col,p_col]).copy()
    sub = sub[sub[p_col].between(0.01,0.99)].sort_values("DATE").reset_index(drop=True)
    if len(sub)<50: return {"n":len(sub),"auc_raw":"<50","brier_raw":"<50","auc_cal":"<50","brier_cal":"<50"}
    yt=sub[y_col].values.astype(float); yp=sub[p_col].values
    auc_raw=round(roc_auc_score(yt,yp),4); brier_raw=round(brier_score_loss(yt,yp),4)
    tss=TimeSeriesSplit(n_splits=5); oof_pos=[]; oof_cal=[]
    for tr,te in tss.split(yt):
        if len(tr)<20: continue
        if use_platt:
            m=PlattLR(C=1e6,solver="lbfgs"); m.fit(yp[tr].reshape(-1,1),yt[tr])
            cp=m.predict_proba(yp[te].reshape(-1,1))[:,1]
        else:
            m=IsotonicRegression(out_of_bounds="clip"); m.fit(yp[tr],yt[tr]); cp=m.predict(yp[te])
        oof_pos.extend(te); oof_cal.extend(cp.tolist())
    if not oof_pos: return {"n":len(sub),"auc_raw":auc_raw,"brier_raw":brier_raw,"auc_cal":"n/a","brier_cal":"n/a"}
    op=np.array(oof_pos); oc=np.array(oof_cal)
    return {"n":len(sub),"auc_raw":auc_raw,"brier_raw":brier_raw,
            "auc_cal":round(roc_auc_score(yt[op],oc),4),"brier_cal":round(brier_score_loss(yt[op],oc),4)}

def edge_table(hr):
    p=hr.dropna(subset=["mkt_spread","home_covered","p_home_cover"]).copy()
    p["home_covered"]=p["home_covered"].astype(float)
    p["edge"]=p["fair_spread"]-(-p["mkt_spread"])
    p["bet_home"]=p["edge"]>0
    p["chosen"]=np.where(p["bet_home"],p["home_covered"],1.0-p["home_covered"])
    p["abs_edge"]=p["edge"].abs()
    p["bucket"]=pd.cut(p["abs_edge"],bins=[0,1.5,3,5,99],labels=["0-1.5","1.5-3","3-5",">5"])
    bkt=p.groupby("bucket",observed=True).agg(n=("chosen","count"),cover_rate=("chosen","mean")).reset_index()
    bkt["ev"]=bkt["cover_rate"].apply(lambda cr:round(ats_ev(cr),4))
    bkt["beats"]=bkt["cover_rate"]>VIG_BE
    return bkt

def run_one(mg, baselines, team_feed, kenpom_dir, tmp):
    pred_f=os.path.join(tmp,f"pred_{mg}.csv"); cal_f=os.path.join(tmp,f"cal_{mg}.csv"); edge_f=os.path.join(tmp,f"edge_{mg}.csv")
    r=subprocess.run([sys.executable,"build_historical_predictions.py",
        "--baselines",baselines,"--team-feed",team_feed,"--kenpom-dir",kenpom_dir,
        "--out-pred",pred_f,"--out-cal",cal_f,"--out-edge",edge_f,"--min-games",str(mg)],
        capture_output=True,text=True)
    if r.returncode!=0: print(f"  ERROR mg={mg}:",r.stderr[-200:]); return None
    preds=pd.read_csv(pred_f,parse_dates=["DATE"])
    hr=preds[preds["VENUE"]=="H/R"].sort_values("DATE").reset_index(drop=True)
    scored=len(preds); n_hr=len(hr)
    n_neut=int((preds["VENUE"]=="Neutral").sum())
    kp_n=int(preds["kenpom_used"].sum()) if "kenpom_used" in preds.columns else 0
    return {"mg":mg,"scored":scored,"hr":n_hr,"neut":n_neut,"kp":kp_n,"bdb":scored-kp_n,
            "ml":oof_metrics(hr,"home_win","p_ml_home",use_platt=True),
            "ats":oof_metrics(hr,"home_covered","p_home_cover"),
            "tot":oof_metrics(hr,"over","p_over"),
            "bkt":edge_table(hr)}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--baselines",default="cbb_cache/TeamBaselines.csv")
    ap.add_argument("--team-feed",default="feeds_daily/03-20-2026-cbb-season-team-feed.xlsx",dest="team_feed")
    ap.add_argument("--kenpom-dir",default="cbb_cache",dest="kenpom_dir")
    args=ap.parse_args()
    tmp=tempfile.mkdtemp(); rows=[]
    for mg in [0,3,5,10]:
        print(f"Running min_games={mg}...",flush=True)
        res=run_one(mg,args.baselines,args.team_feed,args.kenpom_dir,tmp)
        if res: rows.append(res); print(f"  scored={res['scored']} H/R={res['hr']} KP={res['kp']} BDB={res['bdb']}")
    if not rows: return
    ref=next((r for r in rows if r["mg"]==10),rows[-1])
    ref_ats=float(ref["ats"]["auc_raw"]) if isinstance(ref["ats"]["auc_raw"],float) else 0
    ref_tot=float(ref["tot"]["auc_raw"]) if isinstance(ref["tot"]["auc_raw"],float) else 0
    print(f"\n{'='*85}")
    print("MIN_GAMES ABLATION (CSV-based, Platt for ML, Isotonic for ATS/TOT)")
    print(f"{'='*85}")
    print(f"  {'mg':>4} {'scored':>7} {'H/R':>5} {'neut':>5} {'KP':>6} {'BDB':>6} {'ML_r':>7} {'ML_c':>7} {'ATS_r':>6} {'ATS_c':>6} {'TOT_r':>6} {'TOT_c':>6}")
    print(f"  {'-'*80}")
    for r in rows:
        print(f"  {r['mg']:>4} {r['scored']:>7} {r['hr']:>5} {r['neut']:>5} {r['kp']:>6} {r['bdb']:>6} "
              f"{str(r['ml']['auc_raw']):>7} {str(r['ml']['auc_cal']):>7} "
              f"{str(r['ats']['auc_raw']):>6} {str(r['ats']['auc_cal']):>6} "
              f"{str(r['tot']['auc_raw']):>6} {str(r['tot']['auc_cal']):>6}")
    print(f"\n  EDGE BUCKETS:")
    print(f"  {'mg':>4} {'Bucket':<12} {'N':>5} {'CovR':>7} {'EV@-110':>9} {'Vig':>5}")
    for r in rows:
        for _,b in r["bkt"].iterrows():
            print(f"  {r['mg']:>4} {str(b['bucket']):<12} {b['n']:>5} {b['cover_rate']:>7.3f} {b['ev']:>9.4f}{'  ✓' if b['beats'] else ''}")
        print()
    print(f"  DECISION (ΔATS>-0.01 AND ΔTOT>-0.01 vs mg=10, pick smallest mg):")
    chosen=10
    for r in rows:
        try:
            da=float(r["ats"]["auc_raw"])-ref_ats; dt=float(r["tot"]["auc_raw"])-ref_tot
            ok=da>-0.01 and dt>-0.01
            print(f"  mg={r['mg']:>2}: ΔATS={da:+.4f} ΔTOT={dt:+.4f} {'PASS' if ok else 'FAIL'}")
            if ok: chosen=min(chosen,r["mg"])
        except: print(f"  mg={r['mg']:>2}: insufficient data")
    print(f"\n  CHOSEN min_games = {chosen}")

if __name__=="__main__": main()
