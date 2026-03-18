#!/usr/bin/env python3
from pathlib import Path
import pandas as pd
import math

BASE = Path("/Users/josephshackelford/Desktop/SportsBook Training/mmodel_turnkey_complete")
FILES = [
    BASE / "Schedule.csv",
    BASE / "cbb_cache" / "GameInputs.csv",
]
COLS = ["Home spread line (input)", "Game total line (input)"]

def snap_half(x):
    if pd.isna(x):
        return x
    x = float(x)
    return math.copysign(math.floor(abs(x) * 2 + 0.5) / 2, x)

for p in FILES:
    df = pd.read_csv(p)
    before = df[COLS].copy()

    for c in COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce").map(snap_half)

    df.to_csv(p, index=False)

    changed = (before != df[COLS]).any(axis=1)
    print(f"\nPatched {p}")
    if changed.any():
        keep = [c for c in ["Home Team", "Away Team"] + COLS if c in df.columns]
        print(df.loc[changed, keep].to_string(index=False))
    else:
        print("No changes needed.")

# Verification: fail loudly if any off-grid values remain
bad = []
for p in FILES:
    df = pd.read_csv(p)
    for c in COLS:
        vals = pd.to_numeric(df[c], errors="coerce").dropna()
        off = vals[(vals * 2 - (vals * 2).round()).abs() > 1e-9]
        if len(off):
            bad.append((str(p), c, off.tolist()))

if bad:
    print("\nOFF-GRID VALUES STILL PRESENT:")
    for item in bad:
        print(item)
    raise SystemExit(1)

print("\nAll market spread/total inputs are now on the 0.5 grid.")
