"""
build_ff_today_overlay.py — Phase 2 Present-Day FF Overlay
Reads Phase 1 latents. Adds FF overlay using adjust_prices (no custom PMF).
"""
from __future__ import annotations
import argparse, logging, math, sys
import numpy as np
import pandas as pd
from scipy import stats as _stats

logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
log = logging.getLogger("ff_overlay")

FF_K=8.0; LAMBDA_FF=0.30; CLIP_FF=1.5; BLEND_W=0.20
SIGMA_M=11.0; SIGMA_T=18.0; CLIP_GUARD=0.25

def adjust_prices(row, dh, da, pace):
    base_sp=float(row.get("fair_spread",0) or 0)
    base_tt=float(row.get("fair_total",0) or 0)
    sp_r=float(row.get("mkt_spread",float("nan")) or float("nan"))
    tt_r=float(row.get("mkt_total", float("nan")) or float("nan"))
    ff_sp=base_sp+(dh-da)*pace/100.0
    ff_tt=base_tt+(dh+da)*pace/100.0
    if not math.isnan(sp_r):
        ff_ml=float(_stats.norm.cdf(ff_sp/SIGMA_M+0.5))
        ff_cov=float(_stats.norm.cdf((ff_sp-(-sp_r))/SIGMA_M))
    else:
        ff_ml=float(row.get("p_ml_home_raw",0.5) or 0.5)
        ff_cov=None
    ff_ov=(float(1-_stats.norm.cdf((tt_r-ff_tt)/SIGMA_T))
           if not math.isnan(tt_r) else None)
    return {"sp":round(ff_sp,3),"tt":round(ff_tt,3),
            "ml":round(float(np.clip(ff_ml,0.01,0.99)),4),
            "cov":round(float(np.clip(ff_cov,0.01,0.99)),4) if ff_cov else None,
            "ov": round(float(np.clip(ff_ov, 0.01,0.99)),4) if ff_ov  else None}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--latents",   required=True)
    ap.add_argument("--baselines", default="cbb_cache/TeamBaselines.csv")
    ap.add_argument("--kenpom-ff", default="cbb_cache/KenPom_FourFactors_2026.csv",dest="kenpom_ff")
    ap.add_argument("--out",       required=True)
    ap.add_argument("--date",      required=True)
    args=ap.parse_args()

    log.info("="*65)
    log.info("Present-Day FF Overlay (Phase 2 — not historically validated)")
    log.info("="*65)

    if not __import__("os").path.exists(args.latents):
        log.error(f"Latents missing: {args.latents}"); sys.exit(1)
    lat=pd.read_csv(args.latents)
    log.info(f"Latents loaded: {len(lat)} games")

    bas=pd.read_csv(args.baselines,parse_dates=["DATE"])
    bas_today=bas.sort_values("DATE").groupby("KP_NAME").last().reset_index().set_index("KP_NAME")

    # Convert BDB four-factor columns from decimal to percentage if needed
    for col in ["blend_g_eFG","blend_g_TOV","blend_g_ORB","blend_g_FTR",
                "L5_g_eFG","L5_g_TOV","L5_g_ORB","L5_g_FTR",
                "L10_g_eFG","L10_g_TOV","L10_g_ORB","L10_g_FTR"]:
        if col in bas_today.columns and bas_today[col].mean() < 2.0:
            bas_today[col] = bas_today[col] * 100.0

    kp_ff=pd.read_csv(args.kenpom_ff).set_index("TeamName")
    log.info(f"KP FF: {len(kp_ff)} teams  TeamBaselines: {len(bas_today)} teams")

    # League z-score stats from KenPom (all in percentage units)
    lg={}
    for k,c in [("eFG","eFG_Pct"),("TOV","TO_Pct"),("ORB","OR_Pct"),("FTR","FT_Rate"),
                ("DeFG","DeFG_Pct"),("DTO","DTO_Pct"),("DOR","DOR_Pct"),("DFT","DFT_Rate")]:
        if c in kp_ff.columns:
            lg[k+"_mu"]=float(kp_ff[c].mean()); lg[k+"_sd"]=float(kp_ff[c].std()+1e-9)
        else:
            lg[k+"_mu"]=50.0; lg[k+"_sd"]=3.0

    def zs(val,stat): return (float(val)-lg[stat+"_mu"])/lg[stat+"_sd"]

    def blend_off(team,kp_col,bdb_col,w):
        kv=float(kp_ff.loc[team,kp_col]) if kp_col in kp_ff.columns and team in kp_ff.index else lg[kp_col.split("_")[0]+"_mu"]
        bv=float(bas_today.loc[team,bdb_col]) if bdb_col in bas_today.columns and team in bas_today.index else lg["eFG_mu"]
        return w*kv+(1-w)*bv

    def mom_val(team,stat,bdb_col,l5_col,l10_col):
        if team not in bas_today.index: return 0.0
        if bdb_col not in bas_today.columns: return 0.0
        bv=float(bas_today.loc[team,bdb_col])
        l5v=float(bas_today.loc[team,l5_col]) if l5_col in bas_today.columns else bv
        l10v=float(bas_today.loc[team,l10_col]) if l10_col in bas_today.columns else bv
        sd=lg[stat+"_sd"]
        return float(np.clip(0.7*(l5v-bv)/sd+0.3*(l10v-bv)/sd,-1.0,1.0))

    rows_out=[]; clip_hits=0; n_ff=0

    for _,row in lat.iterrows():
        h=str(row["HOME_KP"]); a=str(row["AWAY_KP"])
        out=dict(row)
        out["FairSp_base"]=round(float(row.get("fair_spread",0) or 0),3)
        out["FairTt_base"]=round(float(row.get("fair_total",0)  or 0),3)
        out["P_ML_base"]  =round(float(row.get("p_ml_home_raw",0.5)   or 0.5),4)
        out["P_Cov_base"] =round(float(row.get("p_home_cover_raw",0.5) or 0.5),4)
        out["P_Ov_base"]  =round(float(row.get("p_over_raw",0.5)       or 0.5),4)

        ff_ok=(h in kp_ff.index and a in kp_ff.index
               and h in bas_today.index and a in bas_today.index)

        if not ff_ok:
            out["delta_h_ff"]=0.0; out["delta_a_ff"]=0.0
            out["ff_layer_applied"]=False
            out["ff_validation_status"]="present_day_only_not_historically_validated"
            for pfx in ["FF","final"]:
                out[f"FairSp_{pfx}"]=out["FairSp_base"]; out[f"FairTt_{pfx}"]=out["FairTt_base"]
                out[f"P_ML_{pfx}"]=out["P_ML_base"]; out[f"P_Cov_{pfx}"]=out["P_Cov_base"]; out[f"P_Ov_{pfx}"]=out["P_Ov_base"]
            rows_out.append(out); continue

        gph=float(bas_today.loc[h,"games_played"]) if "games_played" in bas_today.columns else FF_K
        gpa=float(bas_today.loc[a,"games_played"]) if "games_played" in bas_today.columns else FF_K
        wh=FF_K/(FF_K+gph); wa=FF_K/(FF_K+gpa)

        hE=blend_off(h,"eFG_Pct","blend_g_eFG",wh); hT=blend_off(h,"TO_Pct","blend_g_TOV",wh)
        hO=blend_off(h,"OR_Pct","blend_g_ORB",wh);  hF=blend_off(h,"FT_Rate","blend_g_FTR",wh)
        aE=blend_off(a,"eFG_Pct","blend_g_eFG",wa); aT=blend_off(a,"TO_Pct","blend_g_TOV",wa)
        aO=blend_off(a,"OR_Pct","blend_g_ORB",wa);  aF=blend_off(a,"FT_Rate","blend_g_FTR",wa)

        hdE=float(kp_ff.loc[h,"DeFG_Pct"]); hdT=float(kp_ff.loc[h,"DTO_Pct"])
        hdO=float(kp_ff.loc[h,"DOR_Pct"]);  hdF=float(kp_ff.loc[h,"DFT_Rate"])
        adE=float(kp_ff.loc[a,"DeFG_Pct"]); adT=float(kp_ff.loc[a,"DTO_Pct"])
        adO=float(kp_ff.loc[a,"DOR_Pct"]);  adF=float(kp_ff.loc[a,"DFT_Rate"])

        OhE=zs(hE,"eFG"); OhT=-zs(hT,"TOV"); OhO=zs(hO,"ORB"); OhF=zs(hF,"FTR")
        OaE=zs(aE,"eFG"); OaT=-zs(aT,"TOV"); OaO=zs(aO,"ORB"); OaF=zs(aF,"FTR")
        WhE=zs(adE,"DeFG"); WhT=-zs(adT,"DTO"); WhO=-zs(adO,"DOR"); WhF=zs(adF,"DFT")
        WaE=zs(hdE,"DeFG"); WaT=-zs(hdT,"DTO"); WaO=-zs(hdO,"DOR"); WaF=zs(hdF,"DFT")

        Xh_eFG=OhE+WhE; Xh_TOV=OhT+WhT; Xh_ORB=OhO+WhO; Xh_FTR=OhF+WhF
        Xa_eFG=OaE+WaE; Xa_TOV=OaT+WaT; Xa_ORB=OaO+WaO; Xa_FTR=OaF+WaF

        mh_E=mom_val(h,"eFG","blend_g_eFG","L5_g_eFG","L10_g_eFG")
        mh_T=mom_val(h,"TOV","blend_g_TOV","L5_g_TOV","L10_g_TOV")
        mh_O=mom_val(h,"ORB","blend_g_ORB","L5_g_ORB","L10_g_ORB")
        mh_F=mom_val(h,"FTR","blend_g_FTR","L5_g_FTR","L10_g_FTR")
        ma_E=mom_val(a,"eFG","blend_g_eFG","L5_g_eFG","L10_g_eFG")
        ma_T=mom_val(a,"TOV","blend_g_TOV","L5_g_TOV","L10_g_TOV")
        ma_O=mom_val(a,"ORB","blend_g_ORB","L5_g_ORB","L10_g_ORB")
        ma_F=mom_val(a,"FTR","blend_g_FTR","L5_g_FTR","L10_g_FTR")

        raw_h=(1.00*Xh_eFG+0.60*Xh_TOV+0.35*Xh_ORB+0.20*Xh_FTR
               +0.15*mh_E-0.10*mh_T+0.05*mh_O+0.05*mh_F)
        raw_a=(1.00*Xa_eFG+0.60*Xa_TOV+0.35*Xa_ORB+0.20*Xa_FTR
               +0.15*ma_E-0.10*ma_T+0.05*ma_O+0.05*ma_F)

        x_vals=[abs(Xh_eFG),abs(Xh_TOV),abs(Xh_ORB),abs(Xh_FTR),
                abs(Xa_eFG),abs(Xa_TOV),abs(Xa_ORB),abs(Xa_FTR)]
        if max(x_vals)>6:
            log.warning(f"FF GUARD: |X|={max(x_vals):.2f}>6 for {h} vs {a} — using base")
            out["delta_h_ff"]=0.0; out["delta_a_ff"]=0.0; out["ff_layer_applied"]=False
            out["ff_validation_status"]="present_day_only_not_historically_validated"
            for pfx in ["FF","final"]:
                out[f"FairSp_{pfx}"]=out["FairSp_base"]; out[f"FairTt_{pfx}"]=out["FairTt_base"]
                out[f"P_ML_{pfx}"]=out["P_ML_base"]; out[f"P_Cov_{pfx}"]=out["P_Cov_base"]; out[f"P_Ov_{pfx}"]=out["P_Ov_base"]
            rows_out.append(out); continue

        dh=float(np.clip(LAMBDA_FF*raw_h,-CLIP_FF,CLIP_FF))
        da=float(np.clip(LAMBDA_FF*raw_a,-CLIP_FF,CLIP_FF))
        if abs(dh)>=CLIP_FF or abs(da)>=CLIP_FF: clip_hits+=1

        if n_ff<5:
            log.info(f"  [{h} vs {a}]")
            log.info(f"    Xh: eFG={Xh_eFG:+.3f} TOV={Xh_TOV:+.3f} ORB={Xh_ORB:+.3f} FTR={Xh_FTR:+.3f}")
            log.info(f"    Xa: eFG={Xa_eFG:+.3f} TOV={Xa_TOV:+.3f} ORB={Xa_ORB:+.3f} FTR={Xa_FTR:+.3f}")
            log.info(f"    raw_h={raw_h:+.4f} raw_a={raw_a:+.4f}  dh={dh:+.4f} da={da:+.4f}")

        pace=float(row.get("mu_pace",67.5) or 67.5)
        ff_prices=adjust_prices(row,dh,da,pace)
        fin_sp=round(0.80*float(row.get("fair_spread",0) or 0)+0.20*ff_prices["sp"],3)
        fin_tt=round(0.80*float(row.get("fair_total",0)  or 0)+0.20*ff_prices["tt"],3)

        out["delta_h_ff"]=round(dh,4); out["delta_a_ff"]=round(da,4)
        out["ff_layer_applied"]=True
        out["ff_validation_status"]="present_day_only_not_historically_validated"
        out["FairSp_FF"]=ff_prices["sp"]; out["FairTt_FF"]=ff_prices["tt"]
        out["P_ML_FF"]=ff_prices["ml"]; out["P_Cov_FF"]=ff_prices["cov"]; out["P_Ov_FF"]=ff_prices["ov"]
        out["FairSp_final"]=fin_sp; out["FairTt_final"]=fin_tt
        out["P_ML_final"]=ff_prices["ml"]; out["P_Cov_final"]=ff_prices["cov"]; out["P_Ov_final"]=ff_prices["ov"]
        n_ff+=1; rows_out.append(out)

    if n_ff>0 and clip_hits/n_ff>CLIP_GUARD:
        log.warning(f"FF ABORTED: {clip_hits}/{n_ff} hit clip — falling back to base")
        for o in rows_out:
            o["ff_layer_applied"]=False
            for pfx in ["FF","final"]:
                o[f"FairSp_{pfx}"]=o["FairSp_base"]; o[f"FairTt_{pfx}"]=o["FairTt_base"]
                o[f"P_ML_{pfx}"]=o["P_ML_base"]; o[f"P_Cov_{pfx}"]=o["P_Cov_base"]; o[f"P_Ov_{pfx}"]=o["P_Ov_base"]
    else:
        log.info(f"FF overlay: {n_ff} games, {clip_hits} clip hits ({clip_hits/max(n_ff,1):.0%})")

    pd.DataFrame(rows_out).to_csv(args.out,index=False)
    log.info(f"Written: {args.out} ({len(rows_out)} games)")

if __name__=="__main__":
    main()
