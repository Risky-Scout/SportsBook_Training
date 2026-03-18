#!/usr/bin/env python3
"""
kenpom_pull.py (KenPom API DOC-COMPLIANT)

- Base URL: https://kenpom.com
- Endpoint path: /api.php?endpoint=<endpoint>&...
- Auth header: Authorization: Bearer <token>
- Response: JSON

Exports CSVs into out_dir.
"""

from __future__ import annotations
import argparse
import os
from pathlib import Path
import pandas as pd
import requests


def _api_url(base: str) -> str:
    base = base.strip().rstrip("/")
    if base.endswith("/api.php"):
        return base
    return base + "/api.php"


def kp_get(session: requests.Session, base: str, endpoint: str, params: dict) -> pd.DataFrame:
    url = _api_url(base)
    q = {"endpoint": endpoint}
    q.update(params)
    r = session.get(url, params=q, timeout=60)
    r.raise_for_status()
    return pd.DataFrame(r.json())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--out_dir", required=True)
    args = ap.parse_args()

    api_key = os.environ.get("KPC_API_KEY", "").strip()
    base = os.environ.get("KPC_BASE_URL", "https://kenpom.com").strip()
    if not api_key:
        raise RuntimeError("Missing KPC_API_KEY env var")
    if not base:
        raise RuntimeError("Missing KPC_BASE_URL env var")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "ncaab-market-maker/1.0"
    })

    y = int(args.season)
    exports = [
        ("ratings", {"y": y}, f"KenPom_Ratings_{y}.csv"),
        ("four-factors", {"y": y}, f"KenPom_FourFactors_{y}.csv"),
        ("pointdist", {"y": y}, f"KenPom_PointDist_{y}.csv"),
        ("misc-stats", {"y": y}, f"KenPom_MiscStats_{y}.csv"),
        ("height", {"y": y}, f"KenPom_Height_{y}.csv"),
    ]

    for endpoint, params, fname in exports:
        df = kp_get(s, base, endpoint, params)
        df.to_csv(out_dir / fname, index=False)
        print(f"Wrote {fname} ({len(df)} rows)")

    print(f"Saved KenPom exports into {out_dir.resolve()}")


if __name__ == "__main__":
    main()
