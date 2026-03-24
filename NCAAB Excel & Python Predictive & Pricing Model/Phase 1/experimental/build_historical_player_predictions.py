"""
build_historical_player_predictions.py  —  Phase 3B Historical Backtest
========================================================================
Applies player residual layer to every historical game using only
player data strictly BEFORE each game's date. No leakage.

Leakage controls:
  - For game on date D: only player rows with DATE < D are used
  - Recent window = 5 most recent games by DATE before D
  - Season baseline excludes the recent window (no contamination)
  - LOW confidence / insufficient players → zero adjustment (same as production)

Outputs:
  cbb_cache/historical_player_predictions.csv   player-adjusted predictions
  cbb_cache/model_calibration_report_player.csv A/B calibration comparison
  cbb_cache/edge_bucket_table_player.csv        player-adjusted edge buckets

Prints:
  A/B comparison table: team-only vs player-adjusted
  ATS AUC, TOT AUC, Brier raw/cal for both
  Edge buckets with N and EV for both
  Games where |Δspread| >= 1pt and >= 2pt
  Performance split by HIGH vs LOW confidence
"""
from __future__ import annotations
import math, argparse, logging, glob
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import special
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import TimeSeriesSplit
from sklearn.calibration import calibration_curve
from sklearn.linear_model import LinearRegression

logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
log = logging.getLogger("phase3b_hist")

# Frozen production parameters
PHI,SIG,NQ,MX          = 0.004,0.085,9,130
WO,WD                   = 0.55,0.45
LAM_OE,LAM_DE,LAM_TP   = 0.30,0.30,0.20
KP_LG_SYM,KP_LG_TP     = 109.29,67.39
BDB_LG_SYM,BDB_LG_TP   = 106.157,72.270
SA_HOME                 = 1.957
VIG_MULT                = 100.0/110.0
VIG_BREAKEVEN           = 1.0/(1.0+VIG_MULT)
MIN_PLAYERS             = 5
RECENT_N                = 5
ORTG_CLIP               = 8.0
TEMPO_CLIP              = 5.0

def ats_ev(cr): return cr*VIG_MULT-(1.0-cr)

def nb_lpmf(k,mu,phi):
    r=1/phi; p=r/(r+mu)
    return (special.gammaln(k+r)-special.gammaln(r)-special.gammaln(k+1)
            +r*np.log(max(p,1e-12))+k*np.log(max(1-p,1e-12)))

def price_exact(mp,h_ortg,a_ortg,mkt_sp=None,mkt_tt=None):
    pts,wts=np.polynomial.hermite.hermgauss(NQ)
    lmu=math.log(max(mp,1))-0.5*SIG*SIG
    xs=np.arange(MX+1,dtype=float)
    g=np.zeros((MX+1,MX+1)); eh=ea=0.0
    for pt,wt in zip(pts,wts):
        pace=math.exp(lmu+math.sqrt(2)*SIG*pt); wg=wt/math.sqrt(math.pi)
        mh=max(pace*h_ortg/100,0.1); ma=max(pace*a_ortg/100,0.1)
        ph=np.exp(nb_lpmf(xs,mh,PHI)); ph/=ph.sum()
        pa=np.exp(nb_lpmf(xs,ma,PHI)); pa/=pa.sum()
        g+=wg*np.outer(ph,pa); eh+=wg*(xs*ph).sum(); ea+=wg*(xs*pa).sum()
    s=g.sum();
    if s>0: g/=s
    n=MX+1; mg=np.zeros(2*n-1); tg=np.zeros(2*n-1)
    mv=np.arange(-(n-1),n); tv=np.arange(2*n-1)
    for i in range(n):
        np.add.at(mg,i-np.arange(n)+(n-1),g[i]); np.add.at(tg,i+np.arange(n),g[i])
    p_ml=float(mg[mv>0].sum())
    p_cover=float(mg[mv>-mkt_sp].sum()) if mkt_sp is not None else float("nan")
    p_over=float(tg[tv>mkt_tt].sum()) if mkt_tt is not None else float("nan")
    return round(eh-ea,3),round(eh+ea,3),round(p_ml,4),round(p_cover,4),round(p_over,4)


def compute_player_adj(team_name, game_date, player_df):
    """
    Compute player ORtg and tempo adjustment for a team as of game_date.
    Uses only player rows with DATE < game_date (strict no-future).
    Returns (ortg_adj, tempo_adj, confidence, n_players, recency_days, fallback).
    """
    td = player_df[
        (player_df["KP_NAME"] == team_name) &
        (player_df["DATE"] < game_date)
    ].copy()

    if len(td) == 0:
        return 0.0, 0.0, "LOW", 0, 999, "no_data"

    # Get game dates sorted descending
    game_dates = td.groupby("GAME-ID")["DATE"].max().sort_values(ascending=False)
    if len(game_dates) < RECENT_N + 1:
        return 0.0, 0.0, "LOW", 0, 999, "insufficient_games"

    recent_ids = set(game_dates.head(RECENT_N).index)
    season_ids = set(game_dates.tail(len(game_dates)-RECENT_N).index)

    # Filter to players with MIN>=10 minutes
    MIN_THRESH = 10
    recent_df = td[td["GAME-ID"].isin(recent_ids) & (td["MIN"] >= MIN_THRESH)]
    season_df = td[td["GAME-ID"].isin(season_ids) & (td["MIN"] >= MIN_THRESH)]

    if recent_df["PLAYER"].nunique() < MIN_PLAYERS:
        return 0.0, 0.0, "LOW", recent_df["PLAYER"].nunique(), 999, "insufficient_players"

    # PPP = PTS / POSS
    def team_ppp(df):
        if len(df) == 0 or df["POSS"].sum() == 0: return None
        return (df["PTS"] * df["POSS"]).sum() / df["POSS"].sum()

    recent_ppp = team_ppp(recent_df)
    season_ppp = team_ppp(season_df)
    if recent_ppp is None or season_ppp is None:
        return 0.0, 0.0, "LOW", 0, 999, "no_ppp"

    raw_ortg = (recent_ppp - season_ppp) * 100

    # Tempo
    recent_poss = recent_df.groupby("GAME-ID")["POSS"].sum()
    season_poss = season_df.groupby("GAME-ID")["POSS"].sum()
    raw_tempo = (recent_poss.mean() - season_poss.mean()) if len(recent_poss)>0 and len(season_poss)>0 else 0.0

    # Recency
    latest_game = game_dates.index[0]
    latest_date = game_dates.iloc[0]
    recency_days = (game_date - latest_date).days

    # Shrinkage
    n_games = min(len(recent_ids), RECENT_N)
    shrink = (n_games / RECENT_N)
    if recency_days > 14: shrink *= 0.50
    elif recency_days > 7: shrink *= 0.75

    ortg_adj  = float(np.clip(raw_ortg  * shrink, -ORTG_CLIP,  ORTG_CLIP))
    tempo_adj = float(np.clip(raw_tempo * shrink, -TEMPO_CLIP, TEMPO_CLIP))

    n_plyr = recent_df["PLAYER"].nunique()
    conf = "HIGH" if (n_games>=RECENT_N and recency_days<=7 and n_plyr>=7) else \
           "MEDIUM" if n_games>=3 else "LOW"

    return ortg_adj, tempo_adj, conf, n_plyr, recency_days, "none"


def run_calibration_oof(preds_sorted, label):
    tss=TimeSeriesSplit(n_splits=5)
    results=[]
    for name,y_col,p_col in [("ML  (home win)","home_win","p_ml_home"),
                               ("ATS (h cover)","home_covered","p_home_cover"),
                               ("TOT (over)","over","p_over")]:
        sub=preds_sorted.dropna(subset=[y_col,p_col]).copy()
        sub=sub[sub[p_col].between(0.01,0.99)].sort_values("DATE").reset_index(drop=True)
        if len(sub)<100: continue
        yt=sub[y_col].values.astype(float); yp=sub[p_col].values
        bs_raw=brier_score_loss(yt,yp); ll_raw=log_loss(yt,yp); auc_raw=roc_auc_score(yt,yp)
        naive=brier_score_loss(yt,np.full(len(yt),yt.mean()))
        n_bins=min(10,len(sub)//50)
        slope=intercept=float("nan")
        if n_bins>=3:
            pt,pp=calibration_curve(yt,yp,n_bins=n_bins)
            lr=LinearRegression().fit(pp.reshape(-1,1),pt)
            slope=float(lr.coef_[0]); intercept=float(lr.intercept_)
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
        results.append({"subset":label,"market":name,"n_total":len(sub),"n_oof":len(oof_pos),
            "auc_raw":round(auc_raw,4),"auc_cal":round(auc_cal,4),
            "brier_raw":round(bs_raw,4),"brier_cal":round(bs_cal,4),
            "logloss_raw":round(ll_raw,4),"logloss_cal":round(ll_cal,4),
            "cal_slope":round(slope,3) if not math.isnan(slope) else "n/a",
            "cal_intercept":round(intercept,3) if not math.isnan(intercept) else "n/a"})
    return results


def build_edge_table(preds, label):
    p=preds.dropna(subset=["mkt_spread","home_covered","p_home_cover"]).copy()
    p["home_covered"]=p["home_covered"].astype(float)
    p["edge"]=p["fair_spread"]-(-p["mkt_spread"])
    p["bet_home"]=p["edge"]>0
    p["chosen_cover"]=np.where(p["bet_home"],p["home_covered"],1.0-p["home_covered"])
    p["abs_edge"]=p["edge"].abs()
    bins=[0,1.5,3,5,99]; labels=["0-1.5(weak)","1.5-3","3-5",">5"]
    p["bucket"]=pd.cut(p["abs_edge"],bins=bins,labels=labels)
    bkt=p.groupby("bucket",observed=True).agg(
        n=("chosen_cover","count"),
        cover_rate=("chosen_cover","mean"),
        mean_edge=("abs_edge","mean"),
    ).reset_index()
    bkt["ev"]=bkt["cover_rate"].apply(lambda cr:round(ats_ev(cr),4))
    bkt["beats_vig"]=bkt["cover_rate"]>VIG_BREAKEVEN
    bkt["subset"]=label
    return bkt


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--team-pred",   default="cbb_cache/historical_p230_predictions.csv",dest="team_pred")
    ap.add_argument("--player-feed", default="feeds_daily/03-22-2026-cbb-season-player-feed.xlsx",dest="player_feed")
    ap.add_argument("--out-pred",    default="cbb_cache/historical_player_predictions.csv",dest="out_pred")
    ap.add_argument("--out-cal",     default="cbb_cache/model_calibration_report_player.csv",dest="out_cal")
    ap.add_argument("--out-edge",    default="cbb_cache/edge_bucket_table_player.csv",dest="out_edge")
    args=ap.parse_args()

    log.info("="*65)
    log.info("Phase 3B Historical Backtest — Leakage-Safe Player Adjustments")
    log.info("  Player data used: strictly DATE < game_date only")
    log.info("  LOW/insufficient confidence → zero adjustment")
    log.info("="*65)

    # Load team-only historical predictions
    to=pd.read_csv(args.team_pred, parse_dates=["DATE"])
    log.info(f"Team-only predictions: {len(to)} games")

    # Load player feed
    log.info(f"Loading player feed: {args.player_feed}")
    pf=pd.read_excel(args.player_feed, engine="openpyxl")
    pf.columns=[str(c).replace("\n"," ").strip() for c in pf.columns]
    # Normalize column names
    col_map={}
    for c in pf.columns:
        cl=c.lower().replace(" ","")
        if "ownteam" in cl or "ownteam" in c.lower().replace("  ","").replace(" ",""): col_map[c]="KP_NAME"
        elif "playerfull" in cl or (cl.startswith("player") and "id" not in cl): col_map[c]="PLAYER"
        elif cl=="venue(r/h/n)" or "venue" in cl: col_map[c]="VENUE"
        elif cl=="starter(y/n)": col_map[c]="STARTER"
        elif cl=="usagerate(%)" or "usage" in cl: col_map[c]="USAGE"
    pf=pf.rename(columns=col_map)
    pf["DATE"]=pd.to_datetime(pf["DATE"],errors="coerce")
    for col in ["MIN","PTS"]:
        pf[col]=pd.to_numeric(pf[col],errors="coerce")
    # Derive POSS proxy from USAGE RATE if available, else use MIN as weight
    if "USAGE" in pf.columns:
        pf["USAGE"]=pd.to_numeric(pf["USAGE"],errors="coerce").fillna(0)
        pf["POSS"]=pf["USAGE"].clip(lower=0.01)
    else:
        pf["POSS"]=pf["MIN"].clip(lower=0.01)
    pf=pf.dropna(subset=["DATE","PTS","MIN","KP_NAME"]).copy()
    pf=pf[pf["MIN"]>0]
    log.info(f"  {len(pf):,} rows  {pf['DATE'].min().date()} to {pf['DATE'].max().date()}")
    log.info(f"  Columns mapped: KP_NAME={('KP_NAME' in pf.columns)}  PLAYER={('PLAYER' in pf.columns)}")
    if "PLAYER" not in pf.columns:
        pf["PLAYER"]=pf.get("PLAYER-ID","unknown")

    # Apply player adjustments to each historical game
    log.info("Applying player adjustments (leakage-safe)...")
    rows=[]
    n_adjusted=0; n_fallback=0; n_high=0; n_low=0
    batch=max(1,len(to)//10)

    for i,(_,row) in enumerate(to.iterrows()):
        if i%batch==0: log.info(f"  {i}/{len(to)} games...")
        gdate=pd.Timestamp(row["DATE"])

        h_ortg_adj,h_tempo_adj,h_conf,h_nplyr,h_rec,h_fb = compute_player_adj(row["TEAM_h"],gdate,pf)
        a_ortg_adj,a_tempo_adj,a_conf,a_nplyr,a_rec,a_fb = compute_player_adj(row["TEAM_a"],gdate,pf)

        # Delta-spread approach: estimate spread change from ortg adjustments
        # delta_spread = (h_ortg_adj - a_ortg_adj) * avg_pace/100
        # avg_pace estimated at 67.5 possessions (mid-season average)
        AVG_PACE = 67.5
        delta_sp = (h_ortg_adj - a_ortg_adj) * AVG_PACE / 100.0
        delta_tt = (h_ortg_adj + a_ortg_adj) * AVG_PACE / 100.0

        to_spread = float(row["fair_spread"]) if pd.notna(row.get("fair_spread")) else 0.0
        to_total  = float(row["fair_total"])  if pd.notna(row.get("fair_total"))  else 150.0
        fs = round(to_spread + delta_sp, 3)
        ft = round(to_total  + delta_tt, 3)

        mkt_sp=float(row["mkt_spread"]) if pd.notna(row.get("mkt_spread")) else None
        mkt_tt=float(row["mkt_total"])  if pd.notna(row.get("mkt_total"))  else None

        # Update probabilities using normal approximation around new spread
        from scipy import stats as _stats
        SIGMA_M = 11.0; SIGMA_T = 18.0
        to_ml   = float(row["p_ml_home"])  if pd.notna(row.get("p_ml_home"))   else 0.5
        to_cov  = float(row["p_home_cover"]) if pd.notna(row.get("p_home_cover")) else 0.5
        to_ov   = float(row["p_over"])     if pd.notna(row.get("p_over"))      else 0.5

        # Adjust: new_p_cover = Phi((new_spread - (-mkt_spread)) / sigma)
        if mkt_sp is not None:
            p_cov = float(_stats.norm.cdf((fs - (-mkt_sp)) / SIGMA_M))
        else:
            p_cov = to_cov + delta_sp * 0.025   # rough approximation
        if mkt_tt is not None:
            p_ov = float(1 - _stats.norm.cdf((mkt_tt - ft) / SIGMA_T))
        else:
            p_ov = to_ov
        p_ml  = float(_stats.norm.cdf(fs / SIGMA_M))
        p_cov = float(np.clip(p_cov, 0.01, 0.99))
        p_ov  = float(np.clip(p_ov,  0.01, 0.99))
        p_ml  = float(np.clip(p_ml,  0.01, 0.99))

        conf_both="HIGH" if h_conf=="HIGH" and a_conf=="HIGH" else \
                  "MIXED" if (h_conf=="HIGH" or a_conf=="HIGH") else "LOW"
        if h_ortg_adj!=0 or a_ortg_adj!=0: n_adjusted+=1
        else: n_fallback+=1
        if conf_both=="HIGH": n_high+=1
        else: n_low+=1

        rows.append({
            "DATE":str(gdate.date()),"GAME_ID":row.get("GAME_ID"),
            "TEAM_h":row["TEAM_h"],"TEAM_a":row["TEAM_a"],
            "TEAM_h":row["TEAM_h"],"TEAM_a":row["TEAM_a"],
            "VENUE":row.get("VENUE","H/R"),
            "h_ortg_adj":round(h_ortg_adj,3),"a_ortg_adj":round(a_ortg_adj,3),
            "h_conf":h_conf,"a_conf":a_conf,"conf_both":conf_both,
            "fair_spread":round(fs,3),"fair_total":round(ft,3),
            "p_ml_home":round(p_ml,4),"p_home_cover":round(p_cov,4),"p_over":round(p_ov,4),
            "mkt_spread":mkt_sp,"mkt_total":mkt_tt,
            "actual_margin":row["actual_margin"],"actual_total":row["actual_total"],
            "home_win":row["home_win"],
            "home_covered":row.get("home_covered"),"over":row.get("over"),
            # Team-only for comparison
            "to_fair_spread":row["fair_spread"],"to_fair_total":row["fair_total"],
            "to_p_ml":row["p_ml_home"],"to_p_cover":row.get("p_home_cover"),"to_p_over":row.get("p_over"),
            "delta_spread":round(fs-float(row["fair_spread"]),3),
            "delta_total":round(ft-float(row["fair_total"]),3),
        })

    pl_preds=pd.DataFrame(rows)
    pl_preds["DATE"]=pd.to_datetime(pl_preds["DATE"])
    pl_preds=pl_preds.sort_values("DATE").reset_index(drop=True)
    pl_preds.to_csv(args.out_pred,index=False)
    log.info(f"Written: {args.out_pred}  ({len(pl_preds)} games)")
    log.info(f"  Non-zero adjustments: {n_adjusted}  Zero-fallback: {n_fallback}")
    log.info(f"  Both-HIGH: {n_high}  LOW/MIXED: {n_low}")

    # Δspread distribution
    d=pl_preds["delta_spread"].abs()
    n1=int((d>=1).sum()); n2=int((d>=2).sum())
    log.info(f"  |Δspread| >= 1pt: {n1}  |Δspread| >= 2pt: {n2}")

    # Calibration A/B
    log.info("\nRunning OOF calibration (team-only vs player-adjusted)...")
    hr=pl_preds[pl_preds["VENUE"]=="H/R"].sort_values("DATE").reset_index(drop=True)

    # Player-adjusted calibration
    cal_pl=run_calibration_oof(hr,"player_adj")
    # Team-only calibration (using to_p columns)
    hr_to=hr.drop(columns=["p_ml_home","p_home_cover","p_over"],errors="ignore").rename(columns={"to_p_ml":"p_ml_home","to_p_cover":"p_home_cover","to_p_over":"p_over"}).copy()
    cal_to=run_calibration_oof(hr_to,"team_only")

    all_cal=cal_to+cal_pl
    pd.DataFrame(all_cal).to_csv(args.out_cal,index=False)

    # Edge tables
    edge_pl=build_edge_table(pl_preds[pl_preds["VENUE"]=="H/R"],"player_adj")
    edge_to=pl_preds[pl_preds["VENUE"]=="H/R"].copy()
    edge_to["p_home_cover"]=edge_to["to_p_cover"]
    edge_to["fair_spread"]=edge_to["to_fair_spread"]
    edge_to_bkt=build_edge_table(edge_to,"team_only")
    all_edge=pd.concat([edge_to_bkt,edge_pl],ignore_index=True)
    all_edge.to_csv(args.out_edge,index=False)

    # Performance by confidence
    high_games=pl_preds[pl_preds["conf_both"]=="HIGH"].copy()
    low_games=pl_preds[pl_preds["conf_both"]!="HIGH"].copy()

    # PRINT A/B TABLE
    log.info(f"\n{'='*70}")
    log.info("A/B COMPARISON: TEAM-ONLY vs PLAYER-ADJUSTED (H/R games, OOF)")
    log.info(f"{'='*70}")
    log.info(f"  {'Market':<20} {'TO AUC_r':>9} {'TO AUC_c':>9} {'PL AUC_r':>9} {'PL AUC_c':>9} {'ΔAUC_r':>8} {'ΔAUC_c':>8}")
    log.info(f"  {'-'*75}")
    to_map={r["market"]:r for r in cal_to}
    pl_map={r["market"]:r for r in cal_pl}
    for mkt in ["ML  (home win)","ATS (h cover)","TOT (over)"]:
        if mkt not in to_map or mkt not in pl_map: continue
        t=to_map[mkt]; p=pl_map[mkt]
        dauc_r=round(p["auc_raw"]-t["auc_raw"],4)
        dauc_c=round(p["auc_cal"]-t["auc_cal"],4)
        log.info(f"  {mkt:<20} {t['auc_raw']:>9.4f} {t['auc_cal']:>9.4f} {p['auc_raw']:>9.4f} {p['auc_cal']:>9.4f} {dauc_r:>+8.4f} {dauc_c:>+8.4f}")

    log.info(f"\n  {'Market':<20} {'TO Brier_r':>10} {'TO Brier_c':>10} {'PL Brier_r':>10} {'PL Brier_c':>10} {'ΔBrier':>8}")
    log.info(f"  {'-'*75}")
    for mkt in ["ATS (h cover)","TOT (over)"]:
        if mkt not in to_map or mkt not in pl_map: continue
        t=to_map[mkt]; p=pl_map[mkt]
        log.info(f"  {mkt:<20} {t['brier_raw']:>10.4f} {t['brier_cal']:>10.4f} {p['brier_raw']:>10.4f} {p['brier_cal']:>10.4f} {p['brier_raw']-t['brier_raw']:>+8.4f}")

    log.info(f"\n  EDGE BUCKET TABLE (H/R ATS — side-aware):")
    log.info(f"  {'Version':<12} {'Bucket':<14} {'N':>5} {'Cover%':>8} {'EV@-110':>9} {'Vig':>5}")
    log.info(f"  {'-'*55}")
    for _,r in all_edge.iterrows():
        flag=" ✓" if r["beats_vig"] else ""
        log.info(f"  {str(r['subset']):<12} {str(r['bucket']):<14} {r['n']:>5} {r['cover_rate']:>8.3f} {r['ev']:>9.4f}{flag}")

    log.info(f"\n  SPREAD DELTA DISTRIBUTION (all games):")
    log.info(f"    |Δspread| >= 1pt:  {n1} / {len(pl_preds)} games ({100*n1/len(pl_preds):.1f}%)")
    log.info(f"    |Δspread| >= 2pt:  {n2} / {len(pl_preds)} games ({100*n2/len(pl_preds):.1f}%)")

    log.info(f"\n  PERFORMANCE BY CONFIDENCE (ATS H/R only):")
    for label,subset in [("HIGH (both teams)",high_games[high_games["VENUE"]=="H/R"]),
                          ("LOW/MIXED",low_games[low_games["VENUE"]=="H/R"])]:
        sub=subset.dropna(subset=["home_covered","p_home_cover"]).copy()
        if len(sub)<10: continue
        sub["edge"]=sub["fair_spread"]-(-sub["mkt_spread"])
        sub["chosen"]=np.where(sub["edge"]>0,sub["home_covered"].astype(float),1-sub["home_covered"].astype(float))
        ev=ats_ev(sub["chosen"].mean())
        log.info(f"    {label:<25}  n={len(sub):>4}  cover={sub['chosen'].mean():.3f}  EV={ev:+.4f}")

    log.info(f"\n  DECISION RULE:")
    improved=False
    for mkt,thresh in [("ATS (h cover)",0.015),("TOT (over)",0.015)]:
        if mkt not in to_map or mkt not in pl_map: continue
        delta=pl_map[mkt]["auc_raw"]-to_map[mkt]["auc_raw"]
        if abs(delta)>=thresh:
            log.info(f"    {mkt}: ΔAUC={delta:+.4f} {'≥' if delta>=thresh else '<'} threshold {thresh}")
            if delta>=thresh: improved=True
    if improved:
        log.info("    → Player layer MEETS improvement threshold on at least one market")
    else:
        log.info("    → Player layer does NOT meet improvement threshold (ΔAUC < 0.015 on ATS and TOT)")
        log.info("    → Keep player layer in experimental workbook only until threshold is met")

    log.info(f"\n  Written: {args.out_pred}")
    log.info(f"  Written: {args.out_cal}")
    log.info(f"  Written: {args.out_edge}")

if __name__=="__main__": main()
