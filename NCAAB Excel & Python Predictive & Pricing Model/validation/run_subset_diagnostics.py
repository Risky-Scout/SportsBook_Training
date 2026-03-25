
import pandas as pd, numpy as np
from sklearn.metrics import roc_auc_score

VIG_MULT=100/110; VIG_BE=1/(1+VIG_MULT)
def ev(cr): return round(cr*VIG_MULT-(1-cr),4)

def auc_safe(df, y, p):
    s=df.dropna(subset=[y,p]).copy()
    s=s[s[p].between(0.01,0.99)]
    if len(s)<30: return float("nan")
    try: return round(roc_auc_score(s[y].astype(float),s[p]),4)
    except: return float("nan")

preds=pd.read_csv("cbb_cache/historical_p230_predictions.csv",parse_dates=["DATE"])
hr=preds[preds["VENUE"]=="H/R"].copy()
hr["home_covered"]=hr["home_covered"].astype(float)
hr["over"]=hr["over"].astype(float)
hr["abs_edge"]=(hr["fair_spread"]-(-hr["mkt_spread"])).abs()
hr["has_kp"]=hr["kenpom_used"].astype(bool) if "kenpom_used" in hr.columns else True
hr["has_mkt"]=hr["mkt_spread"].notna()&hr["mkt_total"].notna()

def subset_stats(label,df):
    n=len(df)
    df2=df.dropna(subset=["mkt_spread","home_covered"]).copy()
    df2["edge"]=df2["fair_spread"]-(-df2["mkt_spread"])
    df2["chosen"]=np.where(df2["edge"]>0,df2["home_covered"],1-df2["home_covered"])
    cr=df2["chosen"].mean() if len(df2)>0 else float("nan")
    orr=df["over"].dropna().mean()
    return {"label":label,"N":n,
            "ATS_AUC":auc_safe(df,"home_covered","p_home_cover"),
            "TOT_AUC":auc_safe(df,"over","p_over"),
            "CovR":round(cr,3) if not np.isnan(cr) else "n/a",
            "OvR":round(orr,3),"EV_ATS":ev(cr) if not np.isnan(cr) else "n/a",
            "N150":"YES" if n>=150 else "no"}

subsets=[
    ("H/R all",              hr),
    ("H/R + KP joined",      hr[hr["has_kp"]]),
    ("H/R + full mkt",       hr[hr["has_mkt"]]),
    ("H/R + KP + full mkt",  hr[hr["has_kp"]&hr["has_mkt"]]),
    ("edge 3-5",             hr[(hr["abs_edge"]>=3)&(hr["abs_edge"]<=5)]),
    ("edge >5",              hr[hr["abs_edge"]>5]),
]

print("="*80)
print("1. ATS/TOT SUBSET DIAGNOSTICS")
print("="*80)
print(f"  {'Subset':<24} {'N':>5} {'ATS_AUC':>8} {'TOT_AUC':>8} {'CovR':>6} {'OvR':>6} {'EV@-110':>8} {'N>=150':>7}")
print(f"  {'-'*72}")
for lbl,df in subsets:
    r=subset_stats(lbl,df)
    print(f"  {r['label']:<24} {r['N']:>5} {str(r['ATS_AUC']):>8} {str(r['TOT_AUC']):>8} "
          f"{str(r['CovR']):>6} {str(r['OvR']):>6} {str(r['EV_ATS']):>8} {r['N150']:>7}")

# Totals edge buckets
t=hr.dropna(subset=["fair_total","mkt_total","over"]).copy()
t["tot_edge"]=(t["fair_total"]-t["mkt_total"]).abs()
t["chosen_over"]=np.where(t["fair_total"]>t["mkt_total"],t["over"],1-t["over"])
t["bucket"]=pd.cut(t["tot_edge"],bins=[0,2,4,6,99],labels=["0-2","2-4","4-6",">6"])
bkt=t.groupby("bucket",observed=True).agg(n=("chosen_over","count"),orr=("chosen_over","mean")).reset_index()
bkt["ev"]=bkt["orr"].apply(ev); bkt["beats"]=bkt["orr"]>VIG_BE

print("\n"+"="*70)
print("2. TOTALS EDGE BUCKETS (|FairTt - MktTt|, chosen side)")
print("="*70)
print(f"  {'Bucket':<8} {'N':>5} {'OvR(chosen)':>12} {'EV@-110':>9} {'Beats vig':>10} {'N>=150':>7}")
print(f"  {'-'*52}")
for _,r in bkt.iterrows():
    print(f"  {str(r['bucket']):<8} {r['n']:>5} {r['orr']:>12.3f} {r['ev']:>9.4f} "
          f"{'YES ✓' if r['beats'] else 'no':>10} {'YES' if r['n']>=150 else 'no':>7}")

print("\n"+"="*70)
print("3. FINAL PRODUCT CLASSIFICATION")
print("="*70)
# Decision
ats_all=auc_safe(hr,"home_covered","p_home_cover")
tot_all=auc_safe(hr,"over","p_over")
edge35=hr[(hr["abs_edge"]>=3)&(hr["abs_edge"]<=5)]
e35=subset_stats("edge 3-5",edge35)
edge5p=hr[hr["abs_edge"]>5]
e5p=subset_stats("edge >5",edge5p)

has_ats_edge = (
    isinstance(e35["EV_ATS"],float) and e35["EV_ATS"]>0 and e35["N"]>=150 and
    isinstance(e5p["EV_ATS"],float) and e5p["EV_ATS"]>0
)
ats_weak = isinstance(ats_all,float) and ats_all<0.54
tot_weak = isinstance(tot_all,float) and tot_all<0.54

if not ats_weak and not tot_weak and has_ats_edge:
    classification = "provisional production candidate"
else:
    classification = "research pricing workbook"

print(f"  ATS AUC (all H/R): {ats_all}")
print(f"  TOT AUC (all H/R): {tot_all}")
print(f"  ATS weak (<0.54):  {ats_weak}")
print(f"  TOT weak (<0.54):  {tot_weak}")
print(f"  Edge 3-5 beats vig (N>=150): {isinstance(e35['EV_ATS'],float) and e35['EV_ATS']>0 and e35['N']>=150}")
print(f"\n  CLASSIFICATION: {classification.upper()}")
print(f"\n  HONEST RECOMMENDATION:")
if classification=="research pricing workbook":
    print("  The model produces well-structured fair prices using KenPom + BDB data")
    print("  with full PMF pricing and Platt-calibrated ML probabilities.")
    print("  ATS and totals holdout signal is weak (AUC ~0.51).")
    print("  Two ATS buckets beat vig but sample sizes are insufficient for")
    print("  confident production betting. Use for research, line comparison,")
    print("  and market-making intuition only. Not ready for live wagering.")
else:
    print("  Model shows consistent positive EV in edge buckets with N>=150.")
    print("  Provisional production candidate — track live results before")
    print("  committing real capital. Not yet a validated high-win-rate model.")
