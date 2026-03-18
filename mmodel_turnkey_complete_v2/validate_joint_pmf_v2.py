#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path
import pandas as pd

TOL = 1e-8

def check_score_grids(grid_dir: Path) -> list[str]:
    issues = []
    for p in sorted(grid_dir.glob("*.csv")):
        df = pd.read_csv(p)
        if df.empty:
            issues.append(f"{p.name}: empty grid")
            continue
        prob_col = df.columns[-1]
        s = float(df[prob_col].sum())
        if abs(s - 1.0) > TOL:
            issues.append(f"{p.name}: grid PMF sums to {s:.12f}, not 1.0")
    return issues

def check_grouped_pmf(path: Path, label: str) -> list[str]:
    issues = []
    df = pd.read_csv(path)
    if df.empty:
        return [f"{path.name}: empty {label} PMF file"]
    if "PMF" not in df.columns:
        return [f"{path.name}: missing PMF column"]
    grouped = df.groupby(["Cutoff", "Home Team", "Away Team"])["PMF"].sum()
    for idx, s in grouped.items():
        if abs(float(s) - 1.0) > TOL:
            issues.append(f"{label} PMF {idx} sums to {float(s):.12f}, not 1.0")
    return issues

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out_dir", default="./outputs")
    ap.add_argument("--cutoff", required=True)
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    grid_dir = out_dir / "grids"
    margin_path = out_dir / f"exact_margin_pmf_{args.cutoff}.csv"
    total_path = out_dir / f"exact_total_pmf_{args.cutoff}.csv"
    summary_path = out_dir / f"exact_pmf_game_summary_{args.cutoff}.csv"

    missing = [str(p) for p in [grid_dir, margin_path, total_path, summary_path] if not p.exists()]
    if missing:
        raise SystemExit("Missing required Phase 2 outputs:\n- " + "\n- ".join(missing))

    issues = []
    issues += check_score_grids(grid_dir)
    issues += check_grouped_pmf(margin_path, "Margin")
    issues += check_grouped_pmf(total_path, "Total")

    if issues:
        print("PHASE 2 VALIDATION FAILED")
        for x in issues:
            print("-", x)
        raise SystemExit(1)

    print("PHASE 2 VALIDATION PASSED")
    print(f"Validated outputs in: {out_dir}")
    print(f"Cutoff: {args.cutoff}")

if __name__ == "__main__":
    main()
