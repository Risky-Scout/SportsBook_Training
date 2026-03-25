"""
fetch_kenpom.py
===============
Fetches KenPom ratings, four factors, and today's archive snapshot.
Run from repo root:
  python3 fetch_kenpom.py --key YOUR_API_KEY

Saves to cbb_cache/:
  KenPom_Ratings_2026.csv       ← current season ratings
  KenPom_FourFactors_2026.csv   ← current season four factors
  KenPom_Archive_2026-03-21.csv ← today's date-stamped snapshot (leakage-safe historical work)
"""
from __future__ import annotations
import sys, argparse, json, logging
from pathlib import Path
import requests
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
log = logging.getLogger("kenpom")

BASE   = "https://kenpom.com"
SEASON = 2026
TODAY  = "2026-03-21"

def fetch(endpoint: str, params: dict, key: str) -> list[dict]:
    url = f"{BASE}/api.php"
    params["endpoint"] = endpoint
    resp = requests.get(url, params=params,
                        headers={"Authorization": f"Bearer {key}"},
                        timeout=30)
    if resp.status_code != 200:
        log.error(f"  HTTP {resp.status_code} on {endpoint}: {resp.text[:200]}")
        return []
    data = resp.json()
    # API returns either a list or a dict with a data key
    if isinstance(data, list):
        return data
    for k in ("data", "teams", "results"):
        if k in data:
            return data[k]
    return data if isinstance(data, list) else []

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key",    required=True, help="KenPom Bearer API key")
    ap.add_argument("--outdir", default="cbb_cache", help="Output directory")
    ap.add_argument("--season", type=int, default=SEASON)
    ap.add_argument("--date",   default=TODAY, help="Archive date YYYY-MM-DD")
    args = ap.parse_args()

    Path(args.outdir).mkdir(parents=True, exist_ok=True)

    # ── 1. Current ratings ────────────────────────────────────────────────────
    log.info("Fetching ratings...")
    ratings = fetch("ratings", {"y": args.season}, args.key)
    if ratings:
        df_r = pd.DataFrame(ratings)
        out = Path(args.outdir) / f"KenPom_Ratings_{args.season}.csv"
        df_r.to_csv(out, index=False)
        log.info(f"  Ratings: {len(df_r)} teams → {out}")
        log.info(f"  Columns: {list(df_r.columns)}")
        # Print first 3 rows for verification
        log.info(f"  Sample:\n{df_r[['TeamName','AdjOE','AdjDE','AdjTempo']].head(3).to_string()}")
    else:
        log.error("  Ratings fetch failed — check API key and season year")
        return 1

    # ── 2. Four factors ───────────────────────────────────────────────────────
    log.info("Fetching four factors...")
    ff = fetch("four-factors", {"y": args.season}, args.key)
    if ff:
        df_ff = pd.DataFrame(ff)
        out_ff = Path(args.outdir) / f"KenPom_FourFactors_{args.season}.csv"
        df_ff.to_csv(out_ff, index=False)
        log.info(f"  Four factors: {len(df_ff)} teams → {out_ff}")
        # Also write date-stamped FF archive for historical validation
        out_ff_arch = Path(args.outdir) / f"KenPom_FF_Archive_{args.date}.csv"
        df_ff.to_csv(out_ff_arch, index=False)
        log.info(f"  FF archive snapshot: {out_ff_arch}")
        ff_show = [c for c in ["TeamName","eFG_Pct","TO_Pct","OR_Pct","FT_Rate",
                                "DeFG_Pct","DTO_Pct","DOR_Pct","DFT_Rate"] if c in df_ff.columns]
        log.info(f"  Sample:\n{df_ff[ff_show].head(3).to_string()}")
    else:
        log.error("  Four factors fetch failed")
        return 1

    # ── 3. Archive snapshot for today (leakage-safe historical use) ───────────
    log.info(f"Fetching archive snapshot for {args.date}...")
    arch = fetch("archive", {"d": args.date}, args.key)
    if arch:
        df_a = pd.DataFrame(arch)
        out_a = Path(args.outdir) / f"KenPom_Archive_{args.date}.csv"
        df_a.to_csv(out_a, index=False)
        log.info(f"  Archive: {len(df_a)} teams → {out_a}")
        arch_show = [c for c in ["TeamName","AdjOE","AdjDE","AdjTempo","AdjEM"] if c in df_a.columns]
        log.info(f"  Sample:\n{df_a[arch_show].head(3).to_string()}")
    else:
        log.warning("  Archive fetch returned no data — continuing without it")

    # ── 4. Quick crosswalk check ──────────────────────────────────────────────
    crosswalk_path = Path(args.outdir) / "team_crosswalk.csv"
    if crosswalk_path.exists():
        log.info("Checking crosswalk match rate...")
        xw  = pd.read_csv(crosswalk_path)
        kp_names = set(df_r["TeamName"].str.strip())
        xw_kp    = set(xw["KP_NAME"].dropna().str.strip())
        matched  = xw_kp & kp_names
        missing  = xw_kp - kp_names
        log.info(f"  Crosswalk KP_NAME:  {len(xw_kp)} teams")
        log.info(f"  KenPom API:         {len(kp_names)} teams")
        log.info(f"  Exact matches:      {len(matched)}")
        log.info(f"  Missing from API:   {len(missing)}")
        if missing:
            log.warning(f"  Unmatched KP_NAMEs (first 20): {sorted(missing)[:20]}")
    else:
        log.info("  No crosswalk found — skipping match check")

    log.info("Done.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
