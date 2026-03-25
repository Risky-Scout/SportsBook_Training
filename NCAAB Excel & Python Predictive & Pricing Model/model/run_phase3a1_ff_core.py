"""
run_phase3a1_production.py — Phase 3A.1 Team-Only Production Pricing
Mean layer: P2_30 — KenPom backbone + λ=0.30 BDB recency residual
  oe = KP_AdjOE + 0.30*(blend_OEFF - BDB_lg_sym)
  de = KP_AdjDE + 0.30*(blend_DEFF - BDB_lg_sym)
  tp = KP_AdjTempo + 0.20*(blend_POSS  - BDB_lg_tp)
  blg = kp_lg_sym

Ablation 2026-03-21: P0 SD=2.874 corr=0.654 REJECTED | P2_30 corr=0.950 SELECTED
"""
from __future__ import annotations
import sys, math, argparse, logging
from pathlib import Path
import numpy as np, pandas as pd
from scipy import special, optimize

logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
log = logging.getLogger("prod3a1")

PHI,SIG,NQ,MX = 0.004,0.085,9,130
WO,WD = 0.55,0.45
LAM_OE,LAM_DE,LAM_TP = 0.30,0.30,0.20

XWALK = {
    "Iowa State Cyclones":"Iowa St.","Miami Hurricanes":"Miami FL",
    "New Mexico Lobos":"New Mexico","UConn Huskies":"Connecticut",
    "UNLV Rebels":"UNLV","Utah State Aggies":"Utah St.",
    "Vanderbilt Commodores":"Vanderbilt","Virginia Cavaliers":"Virginia",
    "Alabama Crimson Tide":"Alabama","Arizona Wildcats":"Arizona",
    "Arizona State Sun Devils":"Arizona St.","Arkansas Razorbacks":"Arkansas",
    "Auburn Tigers":"Auburn","Baylor Bears":"Baylor","BYU Cougars":"BYU",
    "Colorado State Rams":"Colorado St.","Connecticut Huskies":"Connecticut",
    "Duke Blue Devils":"Duke","Florida Gators":"Florida",
    "Florida State Seminoles":"Florida St.","Georgia Bulldogs":"Georgia",
    "Georgia Tech Yellow Jackets":"Georgia Tech","Gonzaga Bulldogs":"Gonzaga",
    "Houston Cougars":"Houston","Illinois Fighting Illini":"Illinois",
    "Indiana Hoosiers":"Indiana","Iowa Hawkeyes":"Iowa","Kansas Jayhawks":"Kansas",
    "Kansas State Wildcats":"Kansas St.","Kentucky Wildcats":"Kentucky",
    "LSU Tigers":"LSU","Louisville Cardinals":"Louisville",
    "Marquette Golden Eagles":"Marquette","Maryland Terrapins":"Maryland",
    "Memphis Tigers":"Memphis","Michigan Wolverines":"Michigan",
    "Michigan State Spartans":"Michigan St.","Michigan St Spartans":"Michigan St.",
    "Minnesota Golden Gophers":"Minnesota","Mississippi Rebels":"Mississippi",
    "Ole Miss Rebels":"Mississippi","Mississippi State Bulldogs":"Mississippi St.",
    "Missouri Tigers":"Missouri","NC State Wolfpack":"N.C. State",
    "North Carolina Tar Heels":"North Carolina","Northwestern Wildcats":"Northwestern",
    "Notre Dame Fighting Irish":"Notre Dame","Ohio State Buckeyes":"Ohio St.",
    "Oklahoma Sooners":"Oklahoma","Oklahoma State Cowboys":"Oklahoma St.",
    "Oregon Ducks":"Oregon","Oregon State Beavers":"Oregon St.",
    "Penn State Nittany Lions":"Penn St.","Pittsburgh Panthers":"Pittsburgh",
    "Purdue Boilermakers":"Purdue","Rutgers Scarlet Knights":"Rutgers",
    "San Diego State Aztecs":"San Diego St.","South Carolina Gamecocks":"South Carolina",
    "Stanford Cardinal":"Stanford","Syracuse Orange":"Syracuse",
    "TCU Horned Frogs":"TCU","Tennessee Volunteers":"Tennessee",
    "Texas Longhorns":"Texas","Texas A&M Aggies":"Texas A&M",
    "Texas Tech Red Raiders":"Texas Tech","UCLA Bruins":"UCLA","USC Trojans":"USC",
    "Utah Utes":"Utah","Virginia Tech Hokies":"Virginia Tech",
    "Wake Forest Demon Deacons":"Wake Forest","Washington Huskies":"Washington",
    "Washington State Cougars":"Washington St.",
    "West Virginia Mountaineers":"West Virginia","Wisconsin Badgers":"Wisconsin",
    "Xavier Musketeers":"Xavier","High Point Panthers":"High Point",
    "Seattle Redhawks":"Seattle","Seattle U Redhawks":"Seattle",
    "Saint Joseph's Hawks":"Saint Joseph's","St. Joseph's Hawks":"Saint Joseph's",
    "California Golden Bears":"California",
    "George Washington Revolutionaries":"George Washington",
    "Creighton Bluejays":"Creighton",
    "Colorado Buffaloes":"Colorado",
    "Nebraska Cornhuskers":"Nebraska",
    "Tulsa Golden Hurricane":"Tulsa",
    "Wichita St Shockers":"Wichita St.",
    "Dayton Flyers":"Dayton",
    "Illinois St Redbirds":"Illinois St.",
    "St. John's Red Storm":"St. John's",
    "Nevada Wolf Pack":"Nevada",
    "Appalachian State Mountaineers":"Appalachian St.",
    "Sam Houston Bearkats":"Sam Houston St.","Sam Houston State Bearkats":"Sam Houston St.",
}
def R(n): return XWALK.get(str(n).strip(), str(n).strip())

def nb_lpmf(k,mu,phi):
    r=1/phi; p=r/(r+mu)
    return (special.gammaln(k+r)-special.gammaln(r)-special.gammaln(k+1)
            +r*np.log(max(p,1e-12))+k*np.log(max(1-p,1e-12)))

def price_game(mp,h_ortg,a_ortg,sp,tot):
    pts,wts=np.polynomial.hermite.hermgauss(NQ)
    lmu=math.log(max(mp,1))-0.5*SIG*SIG
    g=np.zeros((MX+1,MX+1)); xs=np.arange(MX+1,dtype=float)
    eh=ea=eh2=ea2=eha=0.0; mha=np.zeros(MX+1); maa=np.zeros(MX+1)
    for pt,wt in zip(pts,wts):
        pace=math.exp(lmu+math.sqrt(2)*SIG*pt); wg=wt/math.sqrt(math.pi)
        mh=max(pace*h_ortg/100,0.1); ma=max(pace*a_ortg/100,0.1)
        ph=np.exp(nb_lpmf(xs,mh,PHI)); ph/=ph.sum()
        pa=np.exp(nb_lpmf(xs,ma,PHI)); pa/=pa.sum()
        g+=wg*np.outer(ph,pa); _eh=(xs*ph).sum(); _ea=(xs*pa).sum()
        eh+=wg*_eh; ea+=wg*_ea
        eh2+=wg*((xs**2)*ph).sum(); ea2+=wg*((xs**2)*pa).sum(); eha+=wg*_eh*_ea
        mha+=wg*ph; maa+=wg*pa
    s=g.sum()
    if s>0: g/=s; mha/=mha.sum(); maa/=maa.sum()
    vh=eh2-eh**2; va=ea2-ea**2; cov=eha-eh*ea
    n=g.shape[0]; mg=np.zeros(2*n-1); tg=np.zeros(2*n-1)
    mv=np.arange(-(n-1),n); tv=np.arange(2*n-1)
    for i in range(n):
        np.add.at(mg,i-np.arange(n)+n-1,g[i]); np.add.at(tg,i+np.arange(n),g[i])
    return {"eh":eh,"ea":ea,"gs":g.sum(),
            "sd_m":math.sqrt(max(vh+va-2*cov,0)),"sd_t":math.sqrt(max(vh+va+2*cov,0)),
            "corr":cov/math.sqrt(max(vh*va,1e-9)),
            "p_ml":float(mg[mv>0].sum()),
            "p_hc":float(mg[mv>-sp].sum()) if sp is not None else float("nan"),
            "p_ov":float(tg[tv>tot].sum()) if tot is not None else float("nan"),
            "p_h70":float(mha[70:].sum()),"p_h75":float(mha[75:].sum()),
            "p_a70":float(maa[70:].sum()),"p_a75":float(maa[75:].sum())}

def amer(p):
    if p is None or (isinstance(p,float) and math.isnan(p)): return float("nan")
    p=max(min(float(p),0.9999),0.0001)
    return round(-(p/(1-p))*100) if p>=0.5 else round(((1-p)/p)*100)

def load_slate(path,date_str):
    if not Path(path).exists(): log.error(f"Slate not found: {path}"); return pd.DataFrame()
    df=pd.read_csv(path); df.columns=[str(c).strip() for c in df.columns]
    log.info(f"  Raw columns: {list(df.columns)}")
    A={"Home Team":"HOME_KP","Away Team":"AWAY_KP","Site":"SITE",
       "Home spread line (input)":"mkt_spread","Game total line (input)":"mkt_total",
       "Cutoff":"DATE","HOME":"HOME_KP","AWAY":"AWAY_KP","site":"SITE",
       "SPREAD":"mkt_spread","TOTAL":"mkt_total","spread":"mkt_spread","total":"mkt_total",
       "CLOSING_SPREAD":"mkt_spread","CLOSING_TOTAL":"mkt_total","game_id":"GAME_ID","cutoff":"DATE"}
    df=df.rename(columns={k:v for k,v in A.items() if k in df.columns})
    if "HOME_KP" not in df.columns or "AWAY_KP" not in df.columns:
        log.error(f"Missing HOME_KP/AWAY_KP. Columns: {list(df.columns)}"); return pd.DataFrame()
    if "DATE" not in df.columns: df["DATE"]=date_str
    df["DATE"]=pd.to_datetime(df["DATE"],errors="coerce").fillna(pd.Timestamp(date_str))
    if "GAME_ID" not in df.columns: df["GAME_ID"]=[f"PROD_{date_str}_{i:03d}" for i in range(len(df))]
    if "SITE" not in df.columns: df["SITE"]="H"
    df["SITE"]=df["SITE"].astype(str).str.upper().map(
        {"H":"H","N":"N","HOME":"H","NEUTRAL":"N","ROAD":"H"}).fillna("H")
    mask=df["DATE"].dt.strftime("%Y-%m-%d")==date_str
    if mask.sum()<len(df): df=df[mask].reset_index(drop=True)
    df["HOME_KP"]=df["HOME_KP"].astype(str).str.strip().apply(R)
    df["AWAY_KP"]=df["AWAY_KP"].astype(str).str.strip().apply(R)
    df=df[df["HOME_KP"]!=""].reset_index(drop=True)
    log.info(f"  Slate {date_str}: {len(df)} games  {df['SITE'].value_counts().to_dict()}")
    return df

def team_state_asof(baselines_path,date_str):
    bas=pd.read_csv(baselines_path,parse_dates=["DATE"])
    asof=bas[bas["DATE"]<=pd.Timestamp(date_str)].copy()
    if len(asof)==0: log.error(f"No rows <= {date_str}"); return None
    idx=asof.groupby("KP_NAME")["DATE"].idxmax()
    ts=asof.loc[idx].set_index("KP_NAME")
    lg_sym=(asof["blend_OEFF"].mean()+asof["blend_DEFF"].mean())/2
    lg_tp=asof["blend_POSS"].mean()
    log.info(f"  Baselines as-of {date_str}: {len(asof)} rows  last={asof['DATE'].max().date()}  teams={len(ts)}")
    log.info(f"  BDB lg_sym={lg_sym:.3f}  BDB lg_tp={lg_tp:.3f}")
    return ts,lg_sym,lg_tp

def fit_sa(bp,date_str,kp,kp_lg_sym,kp_lg_tp,bdb_lg_sym,bdb_lg_tp,window=60):
    bas=pd.read_csv(bp,parse_dates=["DATE"])
    cutoff=pd.Timestamp(date_str); start=cutoff-pd.Timedelta(days=window)
    h=bas[(bas["DATE"]>=start)&(bas["DATE"]<cutoff)&(bas["VENUE"]=="Home")]
    a=bas[(bas["DATE"]>=start)&(bas["DATE"]<cutoff)&(bas["VENUE"]=="Road")]
    p=h.merge(a,on="GAME_ID",suffixes=("_h","_a")).dropna(subset=["F_h","F_a"])
    if len(p)<20: log.warning(f"  Only {len(p)} pairs — using 3.5"); return 3.5
    p["margin"]=p["F_h"]-p["F_a"]
    def loss(sa):
        err=[]
        for _,r in p.iterrows():
            hn=R(r.get("KP_NAME_h","")); an=R(r.get("KP_NAME_a",""))
            kh=hn in kp.index; ka=an in kp.index
            koe_h=float(kp.loc[hn,"AdjOE"]) if kh else kp_lg_sym
            kde_h=float(kp.loc[hn,"AdjDE"]) if kh else kp_lg_sym
            ktp_h=float(kp.loc[hn,"AdjTempo"]) if kh else kp_lg_tp
            koe_a=float(kp.loc[an,"AdjOE"]) if ka else kp_lg_sym
            kde_a=float(kp.loc[an,"AdjDE"]) if ka else kp_lg_sym
            ktp_a=float(kp.loc[an,"AdjTempo"]) if ka else kp_lg_tp
            bh=float(r.get("blend_OEFF_h",bdb_lg_sym)); bdh=float(r.get("blend_DEFF_h",bdb_lg_sym))
            ba=float(r.get("blend_OEFF_a",bdb_lg_sym)); bda=float(r.get("blend_DEFF_a",bdb_lg_sym))
            bth=float(r.get("blend_POSS_h",bdb_lg_tp)); bta=float(r.get("blend_POSS_a",bdb_lg_tp))
            oe_h=koe_h+LAM_OE*(bh-bdb_lg_sym); de_h=kde_h+LAM_DE*(bdh-bdb_lg_sym)
            oe_a=koe_a+LAM_OE*(ba-bdb_lg_sym); de_a=kde_a+LAM_DE*(bda-bdb_lg_sym)
            tp_h=ktp_h+LAM_TP*(bth-bdb_lg_tp); tp_a=ktp_a+LAM_TP*(bta-bdb_lg_tp)
            mp=0.85*(2/(1/max(tp_h,50)+1/max(tp_a,50)))+0.15*kp_lg_tp
            oh=kp_lg_sym+WO*(oe_h-kp_lg_sym)+WD*(de_a-kp_lg_sym)+sa
            oa=kp_lg_sym+WO*(oe_a-kp_lg_sym)+WD*(de_h-kp_lg_sym)-sa
            err.append(mp*(oh-oa)/100-float(r["margin"]))
        return float(np.mean(err)**2)
    res=optimize.minimize_scalar(loss,bounds=(0.5,7.0),method="bounded")
    log.info(f"  sa_fit={res.x:.3f} from {len(p)} H/R pairs (last {window}d)")
    return float(res.x)


SLATE_ALIASES = {
    "Cutoff":                     "DATE",
    "Home Team":                  "HOME_KP",
    "Away Team":                  "AWAY_KP",
    "Site":                       "SITE",
    "Home spread line (input)":   "mkt_spread",
    "Game total line (input)":    "mkt_total",
    # already-correct names pass through
    "DATE":"DATE","HOME_KP":"HOME_KP","AWAY_KP":"AWAY_KP","SITE":"SITE",
    "mkt_spread":"mkt_spread","mkt_total":"mkt_total",
}
REQUIRED_COLS = ["DATE","HOME_KP","AWAY_KP","SITE"]

def load_slate(path, date_str):
    import pandas as _pd
    df = _pd.read_csv(path)
    df.columns = [str(c).strip() for c in df.columns]
    log.info(f"  Raw columns: {list(df.columns)}")
    df = df.rename(columns={k:v for k,v in SLATE_ALIASES.items() if k in df.columns})
    log.info(f"  Mapped columns: {list(df.columns)}")
    for c in df.columns:
        if df[c].dtype == object:
            df[c] = df[c].astype(str).str.strip()
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"Slate missing required columns: {missing}")
    if "SITE" in df.columns:
        df["SITE"] = df["SITE"].str.upper().str.strip()
    for col in ["mkt_spread","mkt_total"]:
        if col not in df.columns:
            df[col] = float("nan")
    # Robust date parsing — try multiple formats
    if "DATE" in df.columns:
        raw_dates = df["DATE"].copy()
        # Try direct string match first
        exact = df[df["DATE"] == date_str]
        if len(exact) > 0:
            log.info(f"  Rows before filter: {len(df)}  after date={date_str}: {len(exact)}")
            return exact.copy()
        # Try parsing as datetime
        parsed = _pd.to_datetime(raw_dates, errors="coerce")
        df["DATE_parsed"] = parsed.dt.strftime("%Y-%m-%d")
        unique_dates = df["DATE_parsed"].dropna().unique().tolist()
        log.info(f"  Rows before filter: {len(df)}  unique dates found: {unique_dates}")
        filtered = df[df["DATE_parsed"] == date_str].copy()
        df.drop(columns=["DATE_parsed"], inplace=True, errors="ignore")
        if len(filtered) > 0:
            filtered.drop(columns=["DATE_parsed"], inplace=True, errors="ignore")
            log.info(f"  Rows after date filter ({date_str}): {len(filtered)}")
            return filtered
        # If still 0 — if only one unique date exists, use all rows (single-date file)
        if len(unique_dates) == 1:
            log.warning(f"  Date filter returned 0 for {date_str}, but file has only {unique_dates} — using all {len(df)} rows")
            return df.copy()
        # Hard fail
        log.error(f"  Date filter returned 0 rows for {date_str}. Dates in file: {unique_dates}")
        raise ValueError(f"No games found for date {date_str}. Dates in file: {unique_dates}")
    return df.copy()


_FF_LAMBDA=0.25; _FF_CLIP=1.25; _FF_K=8.0

def _load_ff_core(kp_ff_path, bas_path):
    import pandas as _pd, numpy as _np
    kp = _pd.read_csv(kp_ff_path).set_index("TeamName")
    bas = _pd.read_csv(bas_path, parse_dates=["DATE"])
    bas_t = bas.sort_values("DATE").groupby("KP_NAME").last()
    lg = {}
    for k,c in [("eFG","eFG_Pct"),("TOV","TO_Pct"),("ORB","OR_Pct"),("FTR","FT_Rate"),
                ("DeFG","DeFG_Pct"),("DTO","DTO_Pct"),("DOR","DOR_Pct"),("DFT","DFT_Rate")]:
        lg[k+"_mu"]=float(kp[c].mean()); lg[k+"_sd"]=float(kp[c].std()+1e-9)
    for k,c in [("eFG","blend_g_eFG"),("TOV","blend_g_TOV"),("ORB","blend_g_ORB"),("FTR","blend_g_FTR")]:
        if c in bas_t.columns:
            v=bas_t[c].dropna()
            vals=v*100 if v.mean()<2 else v
            lg["b"+k+"_sd"]=float(vals.std()+1e-9)
        else: lg["b"+k+"_sd"]=3.0
    teams={}
    for team in kp.index:
        if team not in bas_t.index: continue
        b=bas_t.loc[team]; gp=float(b.get("games_played",_FF_K))
        w=_FF_K/(_FF_K+gp)
        def bv(c,fb):
            val=float(b[c]) if c in b.index else fb
            return val*100 if val<2.0 else val
        off={"eFG":w*float(kp.loc[team,"eFG_Pct"])+(1-w)*bv("blend_g_eFG",50),
             "TOV":w*float(kp.loc[team,"TO_Pct"]) +(1-w)*bv("blend_g_TOV",17),
             "ORB":w*float(kp.loc[team,"OR_Pct"]) +(1-w)*bv("blend_g_ORB",30),
             "FTR":w*float(kp.loc[team,"FT_Rate"])+(1-w)*bv("blend_g_FTR",35)}
        dff={"DeFG":float(kp.loc[team,"DeFG_Pct"]),"DTO":float(kp.loc[team,"DTO_Pct"]),
             "DOR":float(kp.loc[team,"DOR_Pct"]), "DFT":float(kp.loc[team,"DFT_Rate"])}
        mom={}
        for k,bc,l5,l10 in [("eFG","blend_g_eFG","L5_g_eFG","L10_g_eFG"),
                              ("TOV","blend_g_TOV","L5_g_TOV","L10_g_TOV"),
                              ("ORB","blend_g_ORB","L5_g_ORB","L10_g_ORB"),
                              ("FTR","blend_g_FTR","L5_g_FTR","L10_g_FTR")]:
            if bc in b.index and l5 in b.index and l10 in b.index:
                bval=bv(bc,50); l5v=bv(l5,bval); l10v=bv(l10,bval)
                sd=lg["b"+k+"_sd"]
                mom[k]=float(_np.clip(0.7*(l5v-bval)/sd+0.3*(l10v-bval)/sd,-1,1))
            else: mom[k]=0.0
        teams[team]={"off":off,"def":dff,"mom":mom}
    return teams, lg

def _ff_delta(ht, at, lg):
    def zo(v,k): return (v-lg[k+"_mu"])/lg[k+"_sd"]
    OhE= zo(ht["off"]["eFG"],"eFG"); OhT=-zo(ht["off"]["TOV"],"TOV")
    OhO= zo(ht["off"]["ORB"],"ORB"); OhF= zo(ht["off"]["FTR"],"FTR")
    OaE= zo(at["off"]["eFG"],"eFG"); OaT=-zo(at["off"]["TOV"],"TOV")
    OaO= zo(at["off"]["ORB"],"ORB"); OaF= zo(at["off"]["FTR"],"FTR")
    WhE= zo(at["def"]["DeFG"],"DeFG"); WhT=-zo(at["def"]["DTO"],"DTO")
    WhO=-zo(at["def"]["DOR"],"DOR");  WhF= zo(at["def"]["DFT"],"DFT")
    WaE= zo(ht["def"]["DeFG"],"DeFG"); WaT=-zo(ht["def"]["DTO"],"DTO")
    WaO=-zo(ht["def"]["DOR"],"DOR");  WaF= zo(ht["def"]["DFT"],"DFT")
    Xh=[OhE+WhE,OhT+WhT,OhO+WhO,OhF+WhF]
    Xa=[OaE+WaE,OaT+WaT,OaO+WaO,OaF+WaF]
    mh=ht["mom"]; ma=at["mom"]
    rh=1.00*Xh[0]+0.60*Xh[1]+0.35*Xh[2]+0.20*Xh[3]+0.15*mh["eFG"]-0.10*mh["TOV"]+0.05*mh["ORB"]+0.05*mh["FTR"]
    ra=1.00*Xa[0]+0.60*Xa[1]+0.35*Xa[2]+0.20*Xa[3]+0.15*ma["eFG"]-0.10*ma["TOV"]+0.05*ma["ORB"]+0.05*ma["FTR"]
    x_all=[abs(x) for x in Xh+Xa]
    guard=max(x_all)>6
    import numpy as _np
    dh=float(_np.clip(_FF_LAMBDA*rh,-_FF_CLIP,_FF_CLIP))
    da=float(_np.clip(_FF_LAMBDA*ra,-_FF_CLIP,_FF_CLIP))
    return dh,da,guard

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--slate",     default="cbb_cache/GameInputs.csv")
    ap.add_argument("--baselines", default="cbb_cache/TeamBaselines.csv")
    ap.add_argument("--kenpom",    default="cbb_cache/KenPom_Ratings_2026.csv")
    ap.add_argument("--kenpom-ff", default="cbb_cache/KenPom_FourFactors_2026.csv",dest="kenpom_ff")
    ap.add_argument("--output",    default="cbb_cache/MatchupLatents_today_teamonly.csv")
    ap.add_argument("--date",      default="2026-03-21")
    args=ap.parse_args()

    log.info("="*65)
    log.info("Phase 3A.1 — team_only_v1_p2_30")
    log.info(f"  Date={args.date}  phi={PHI}  sigma={SIG}")
    log.info(f"  Mean layer: P2_30  lam_oe={LAM_OE}  lam_de={LAM_DE}  lam_tp={LAM_TP}")
    log.info("="*65)

    slate=load_slate(args.slate,args.date)
    if len(slate)==0: sys.exit(1)

    obj=team_state_asof(args.baselines,args.date)
    if obj is None: sys.exit(1)
    ts,bdb_lg_sym,bdb_lg_tp=obj

    kp=pd.read_csv(args.kenpom); kp["TeamName"]=kp["TeamName"].str.strip(); kp=kp.set_index("TeamName")
    kp_lg_sym=(kp["AdjOE"].mean()+kp["AdjDE"].mean())/2; kp_lg_tp=kp["AdjTempo"].mean()
    log.info(f"  KenPom: {len(kp)} teams  kp_lg_sym={kp_lg_sym:.2f}  kp_lg_tp={kp_lg_tp:.2f}")

    sa_fit=fit_sa(args.baselines,args.date,kp,kp_lg_sym,kp_lg_tp,bdb_lg_sym,bdb_lg_tp)

    def gs(t,col,fb):
        if t in ts.index:
            v=ts.loc[t,col]; return float(v) if pd.notna(v) else fb
        return fb

    _ff_teams,_ff_lg=_load_ff_core(args.kenpom_ff,args.baselines)
    log.info(f"FF core teams loaded: {len(_ff_teams)}")
    rows=[]; kp_both=0; kp_miss=[]
    for _,game in slate.iterrows():
        h=str(game["HOME_KP"]); a=str(game["AWAY_KP"])
        site=str(game.get("SITE","H")).upper()
        if site not in("H","N"): site="H"

        h=R(h); a=R(a)
        kh=h in kp.index; ka=a in kp.index
        if kh and ka: kp_both+=1
        else: kp_miss.append(f"{h}(kp={kh}) vs {a}(kp={ka})")

        kp_oe_h=float(kp.loc[h,"AdjOE"])    if kh else kp_lg_sym
        kp_de_h=float(kp.loc[h,"AdjDE"])    if kh else kp_lg_sym
        kp_tp_h=float(kp.loc[h,"AdjTempo"]) if kh else kp_lg_tp
        kp_oe_a=float(kp.loc[a,"AdjOE"])    if ka else kp_lg_sym
        kp_de_a=float(kp.loc[a,"AdjDE"])    if ka else kp_lg_sym
        kp_tp_a=float(kp.loc[a,"AdjTempo"]) if ka else kp_lg_tp

        bdb_oe_h=gs(h,"blend_OEFF",bdb_lg_sym); bdb_de_h=gs(h,"blend_DEFF",bdb_lg_sym); bdb_tp_h=gs(h,"blend_POSS",bdb_lg_tp)
        bdb_oe_a=gs(a,"blend_OEFF",bdb_lg_sym); bdb_de_a=gs(a,"blend_DEFF",bdb_lg_sym); bdb_tp_a=gs(a,"blend_POSS",bdb_lg_tp)
        h_gpd1=gs(h,"games_played",30); a_gpd1=gs(a,"games_played",30)
        h_qual=str(ts.loc[h,"data_quality"]) if h in ts.index else "NO_STATE"
        a_qual=str(ts.loc[a,"data_quality"]) if a in ts.index else "NO_STATE"

        oe_h=kp_oe_h+LAM_OE*(bdb_oe_h-bdb_lg_sym)
        de_h=kp_de_h+LAM_DE*(bdb_de_h-bdb_lg_sym)
        tp_h=kp_tp_h+LAM_TP*(bdb_tp_h-bdb_lg_tp)
        oe_a=kp_oe_a+LAM_OE*(bdb_oe_a-bdb_lg_sym)
        de_a=kp_de_a+LAM_DE*(bdb_de_a-bdb_lg_sym)
        tp_a=kp_tp_a+LAM_TP*(bdb_tp_a-bdb_lg_tp)
        blg=kp_lg_sym

        sa=sa_fit if site=="H" else 0.0
        harm=2/(1/max(tp_h,50)+1/max(tp_a,50)); mp=0.85*harm+0.15*kp_lg_tp
        h_ortg_base=blg+WO*(oe_h-blg)+WD*(de_a-blg)+sa
        a_ortg_base=blg+WO*(oe_a-blg)+WD*(de_h-blg)-sa
        _hkp=R(h); _akp=R(a)
        if _hkp in _ff_teams and _akp in _ff_teams:
            _dh,_da,_gf=_ff_delta(_ff_teams[_hkp],_ff_teams[_akp],_ff_lg)
            _ff_app=not _gf
        else: _dh=0.0; _da=0.0; _ff_app=False
        h_ortg=h_ortg_base+(_dh if _ff_app else 0.0)
        a_ortg=a_ortg_base+(_da if _ff_app else 0.0)
        h_ortg_core=h_ortg; a_ortg_core=a_ortg

        sp_r=float(game.get("mkt_spread",float("nan")) or float("nan"))
        tt_r=float(game.get("mkt_total", float("nan")) or float("nan"))
        sp=sp_r if not math.isnan(sp_r) else None
        tt=tt_r if not math.isnan(tt_r) else None

        pmf=price_game(mp,h_ortg,a_ortg,sp,tt)
        if abs(pmf["gs"]-1)>1e-8:
            log.warning(f"  PMF gs={pmf['gs']:.8f} for {h} vs {a}"); continue

        rows.append({
            "GAME_ID":game.get("GAME_ID",f"PROD_{args.date}"),
            "DATE":args.date,"HOME_KP":h,"AWAY_KP":a,"SITE":site,
            "model_version":"team_only_v1_p2_30",
            "mean_layer":"KP_backbone_plus_BDB_lambda_0.30",
            "KP_AdjOE_h":round(kp_oe_h,3),"KP_AdjDE_h":round(kp_de_h,3),"KP_AdjTempo_h":round(kp_tp_h,3),
            "KP_AdjOE_a":round(kp_oe_a,3),"KP_AdjDE_a":round(kp_de_a,3),"KP_AdjTempo_a":round(kp_tp_a,3),
            "bdb_blend_OEFF_h":round(bdb_oe_h,3),"bdb_blend_DEFF_h":round(bdb_de_h,3),"bdb_blend_POSS_h":round(bdb_tp_h,3),
            "bdb_blend_OEFF_a":round(bdb_oe_a,3),"bdb_blend_DEFF_a":round(bdb_de_a,3),"bdb_blend_POSS_a":round(bdb_tp_a,3),
            "h_gpd1":int(h_gpd1),"a_gpd1":int(a_gpd1),
            "oe_h":round(oe_h,3),"de_h":round(de_h,3),"tp_h":round(tp_h,3),
            "oe_a":round(oe_a,3),"de_a":round(de_a,3),"tp_a":round(tp_a,3),
            "blend_lg":round(blg,3),"sa_used":round(sa,3),"mu_pace":round(mp,3),
            "h_ortg_base":round(h_ortg_base,3),"a_ortg_base":round(a_ortg_base,3),"delta_h_ff":round(_dh,4),"delta_a_ff":round(_da,4),"h_ortg_core":round(h_ortg_core,3),"a_ortg_core":round(a_ortg_core,3),"ff_layer_applied":_ff_app,"ff_layer_status":"direct_core_present_day_only" if _ff_app else "base_only","h_ortg":round(h_ortg,3),"a_ortg":round(a_ortg,3),
            "mu_home":round(mp*h_ortg/100,3),"mu_away":round(mp*a_ortg/100,3),
            "fair_spread":round(pmf["eh"]-pmf["ea"],3),"fair_total":round(pmf["eh"]+pmf["ea"],3),"FairSp_core":round(pmf["eh"]-pmf["ea"],3),"FairTt_core":round(pmf["eh"]+pmf["ea"],3),"P_ML_core":round(pmf["p_ml"],4),"P_Cov_core":(round(pmf["p_hc"],4) if not math.isnan(pmf["p_hc"]) else float("nan")),"P_Ov_core":(round(pmf["p_ov"],4) if not math.isnan(pmf["p_ov"]) else float("nan")),
            "fair_home_team_total":round(pmf["eh"],3),"fair_away_team_total":round(pmf["ea"],3),
            "p_ml_home_raw":round(pmf["p_ml"],4),
            "p_home_cover_raw":round(pmf["p_hc"],4) if not math.isnan(pmf["p_hc"]) else float("nan"),
            "p_over_raw":round(pmf["p_ov"],4) if not math.isnan(pmf["p_ov"]) else float("nan"),
            "p_h_gt70":round(pmf["p_h70"],4),"p_h_gt75":round(pmf["p_h75"],4),
            "p_a_gt70":round(pmf["p_a70"],4),"p_a_gt75":round(pmf["p_a75"],4),
            "fair_ml_home_american":amer(pmf["p_ml"]),"fair_ml_away_american":amer(1-pmf["p_ml"]),
            "edge_spread_pts":round((pmf["eh"]-pmf["ea"])-(-sp_r),3) if not math.isnan(sp_r) else float("nan"),
            "edge_total_pts":round((pmf["eh"]+pmf["ea"])-tt_r,3) if not math.isnan(tt_r) else float("nan"),
            "pred_sd_margin":round(pmf["sd_m"],3),"pred_sd_total":round(pmf["sd_t"],3),
            "pred_corr_ha":round(pmf["corr"],4),
            "player_ortg_adj_h":0.0,"player_ortg_adj_a":0.0,
            "tempo_adj_h":0.0,"tempo_adj_a":0.0,
            "rotation_delta_h":0.0,"rotation_delta_a":0.0,
            "player_layer_applied":False,
            "kenpom_used":kh and ka,"kenpom_h_joined":kh,"kenpom_a_joined":ka,
            "h_data_quality":h_qual,"a_data_quality":a_qual,
            "pmf_grid_sum":round(pmf["gs"],10),
            "phi_used":PHI,"sigma_used":SIG,
            "lam_oe":LAM_OE,"lam_de":LAM_DE,"lam_tp":LAM_TP,
            "mkt_spread":sp_r,"mkt_total":tt_r,
        })

    result=pd.DataFrame(rows)
    if len(result)==0:
        log.error("No games scored — output NOT written to prevent stale file contamination")
        import os; 
        if os.path.exists(args.output): os.remove(args.output)
        sys.exit(1)
    Path(args.output).parent.mkdir(parents=True,exist_ok=True)
    result.to_csv(args.output,index=False)

    log.info(f"\n{'='*65}\nVERIFICATION SUMMARY (team_only_v1_p2_30)\n{'='*65}")
    log.info(f"  Scored:                      {len(result)}")
    log.info(f"  H/R: {(result['SITE']=='H').sum()}  Neutral: {(result['SITE']=='N').sum()}")
    log.info(f"  KenPom both joined:          {result['kenpom_used'].sum()} / {len(result)}")
    log.info(f"  BDB-only fallback:           {(~result['kenpom_used']).sum()}")
    if kp_miss: log.warning(f"  Misses: {kp_miss}")
    log.info(f"  player_layer_applied=False:  {(~result['player_layer_applied']).all()}")
    log.info(f"  model_version:               team_only_v1_p2_30")
    log.info(f"  PMF max grid_sum err:        {(result['pmf_grid_sum']-1).abs().max():.2e}")
    log.info(f"  Games w/ mkt_spread:         {result['mkt_spread'].notna().sum()}")
    log.info(f"  Games w/ mkt_total:          {result['mkt_total'].notna().sum()}")
    log.info(f"\n  DISTRIBUTIONS:")
    for col in ["fair_spread","fair_total","pred_sd_margin","pred_sd_total","pred_corr_ha"]:
        v=result[col].dropna().astype(float)
        log.info(f"    {col:<24}: mean={v.mean():+.3f}  SD={v.std():.3f}  min={v.min():+.3f}  max={v.max():+.3f}")
    if result["mkt_spread"].notna().sum()>3:
        both=result.dropna(subset=["fair_spread","mkt_spread"])
        c=float(np.corrcoef(both["fair_spread"],-both["mkt_spread"])[0,1])
        mad=float((both["fair_spread"]-(-both["mkt_spread"])).abs().mean())
        log.info(f"    corr(fair_spread,-mkt_spread): {c:.4f}  {'PASS' if c>=0.80 else 'CHECK'}")
        log.info(f"    MAD vs market:                 {mad:.3f} pts")
    log.info(f"\n  SAMPLE TRACES (first 5):")
    for _,r in result.head(5).iterrows():
        log.info(f"    [{r['HOME_KP']} vs {r['AWAY_KP']}] site={r['SITE']} kp={r['kenpom_used']}")
        log.info(f"      KP_OE_h={r['KP_AdjOE_h']:.2f} bdb_oe={r['bdb_blend_OEFF_h']:.2f} -> oe_h={r['oe_h']:.3f}")
        log.info(f"      KP_DE_h={r['KP_AdjDE_h']:.2f} bdb_de={r['bdb_blend_DEFF_h']:.2f} -> de_h={r['de_h']:.3f}")
        log.info(f"      h_ortg={r['h_ortg']:.3f}  a_ortg={r['a_ortg']:.3f}  pace={r['mu_pace']:.3f}  sa={r['sa_used']:.3f}")
        log.info(f"      spread={r['fair_spread']:+.3f}  total={r['fair_total']:.3f}  p_ml={r['p_ml_home_raw']:.4f}")
        log.info(f"      mkt_spread={r['mkt_spread']}  mkt_total={r['mkt_total']}  grid={r['pmf_grid_sum']:.8f}")
    log.info(f"\n  Written: {args.output}")
    log.info("  NEXT: python3 build_team_only_workbook_v1.py")

if __name__=="__main__": main()
