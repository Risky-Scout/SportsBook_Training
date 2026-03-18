#!/usr/bin/env python3
"""build_cbb_cache.py

Reads BigDataBall season feeds (TEAM + PLAYER) and produces small cache tables:

Outputs to --out_dir:
  TeamSnapshot.csv            (one row per team; season + last10)
  TeamPlayerIndex.csv         (one row per team; ROT_DELTA_VALUE injury proxy)
  PlayerRotationSnapshot.csv  (top 10 players per team by minutes; optional)
  TeamGameLog_Last30D.csv     (optional)

This keeps Excel fast while preserving full feed fidelity.
"""

from __future__ import annotations
import argparse
from pathlib import Path
import pandas as pd
import numpy as np

TEAM_SHEET = "CBB-2025-26-TEAM"
PLAYER_SHEET = "CBB-2025-26-PLAYER"

def load_team(team_file: Path, cutoff: str) -> pd.DataFrame:
    df = pd.read_excel(team_file, sheet_name=TEAM_SHEET)
    df.columns = [str(c).strip() for c in df.columns]
    if "DATE" not in df.columns:
        raise KeyError("TEAM sheet missing DATE column")
    df["DATE"] = pd.to_datetime(df["DATE"], errors="coerce")
    df = df[df["DATE"].notna()].copy()
    df = df[df["DATE"] <= pd.Timestamp(cutoff)].copy()
    # normalize team name col
    if "TEAM" not in df.columns and "OWN TEAM" in df.columns:
        df["TEAM"] = df["OWN TEAM"]
    if "TEAM" not in df.columns:
        raise KeyError("TEAM sheet missing TEAM (or OWN TEAM) column")

    # numeric fields (best effort)
    for c in ["PACE","OEFF","DEFF","PTS","POSS"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

def load_player(player_file: Path, cutoff: str) -> pd.DataFrame:
    df = pd.read_excel(player_file, sheet_name=PLAYER_SHEET)
    # normalize headers (fixes OWN \nTEAM, tabs, double-spaces)
    df.columns = df.columns.astype(str).str.replace(r"\s+"," ", regex=True).str.strip()
    df.columns = [str(c).strip() for c in df.columns]
    if "DATE" not in df.columns:
        raise KeyError("PLAYER sheet missing DATE column")
    df["DATE"] = pd.to_datetime(df["DATE"], errors="coerce")
    df = df[df["DATE"].notna()].copy()
    df = df[df["DATE"] <= pd.Timestamp(cutoff)].copy()
    if "TEAM" not in df.columns and "OWN TEAM" in df.columns:
        df["TEAM"] = df["OWN TEAM"]
    if "TEAM" not in df.columns:
        raise KeyError("PLAYER sheet missing TEAM (or OWN TEAM) column")
    for c in ["MIN","USAGE RATE (%)","PTS"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "USAGE RATE (%)" in df.columns and "USG_PCT" not in df.columns:
        df["USG_PCT"] = df["USAGE RATE (%)"]
    return df

def team_snapshot(team: pd.DataFrame, last_n: int=10) -> pd.DataFrame:
    team = team.sort_values(["TEAM","DATE"])
    g = team.groupby("TEAM", as_index=False).agg(
        GAMES=("DATE","count"),
        OEFF=("OEFF","mean"),
        DEFF=("DEFF","mean"),
        PACE=("PACE","mean"),
        PTS=("PTS","mean") if "PTS" in team.columns else ("OEFF","mean"),
    )
    last = (team.groupby("TEAM", as_index=False).tail(last_n)
                .groupby("TEAM", as_index=False)
                .agg(L10_OEFF=("OEFF","mean"), L10_DEFF=("DEFF","mean"), L10_PACE=("PACE","mean")))
    out = g.merge(last, on="TEAM", how="left")
    out["EM"] = out["OEFF"] - out["DEFF"]
    out["L10_EM"] = out["L10_OEFF"] - out["L10_DEFF"]
    return out

def rotation_proxy(player: pd.DataFrame, recent_n: int=5, top_k: int=8) -> pd.DataFrame:
    df = player.sort_values(["TEAM","DATE"]).copy()
    # minutes per player season avg
    season = df.groupby(["TEAM","PLAYERID"] if "PLAYERID" in df.columns else ["TEAM","PLAYER FULL NAME"], as_index=False).agg(
        MIN_SEASON=("MIN","mean"),
        GP=("DATE","count"),
    )
    keycols = ["TEAM"]
    pidcol = "PLAYERID" if "PLAYERID" in df.columns else ("PLAYER FULL NAME" if "PLAYER FULL NAME" in df.columns else "PLAYER")
    season = season.rename(columns={pidcol:"PID"}) if pidcol in season.columns else season
    # recent avg
    recent = (df.groupby(["TEAM", pidcol], as_index=False).tail(recent_n)
                .groupby(["TEAM", pidcol], as_index=False).agg(MIN_RECENT=("MIN","mean")))
    recent = recent.rename(columns={pidcol:"PID"})
    m = season.merge(recent, on=["TEAM","PID"], how="left")
    m["MIN_RECENT"] = m["MIN_RECENT"].fillna(0.0)
    # pick top_k by season minutes
    m["RANK"] = m.groupby("TEAM")["MIN_SEASON"].rank(method="first", ascending=False)
    rot = m[m["RANK"]<=top_k].copy()
    # availability ratio
    rot["RATIO"] = np.where(rot["MIN_SEASON"]>0, rot["MIN_RECENT"]/rot["MIN_SEASON"], 0.0)
    # weight by season minute share within top_k
    rot["W"] = rot["MIN_SEASON"] / rot.groupby("TEAM")["MIN_SEASON"].transform("sum")
    team_avail = rot.groupby("TEAM", as_index=False).apply(lambda g: pd.Series({
        "ROT_AVAIL": float((g["RATIO"]*g["W"]).sum())
    }))
    team_avail["ROT_DELTA_VALUE"] = team_avail["ROT_AVAIL"] - 1.0
    return team_avail[["TEAM","ROT_AVAIL","ROT_DELTA_VALUE"]]

def player_rotation_snapshot(player: pd.DataFrame, top_k: int=10) -> pd.DataFrame:
    pidcol = "PLAYER FULL NAME" if "PLAYER FULL NAME" in player.columns else ("PLAYER_NAME" if "PLAYER_NAME" in player.columns else ("PLAYER" if "PLAYER" in player.columns else None))
    if pidcol is None:
        return pd.DataFrame()
    p = player.groupby(["TEAM", pidcol], as_index=False).agg(GP=("DATE","count"), MIN_AVG=("MIN","mean"), USG_AVG=("USG_PCT","mean"), PTS_AVG=("PTS","mean"))
    p["MIN_RANK"] = p.groupby("TEAM")["MIN_AVG"].rank(method="first", ascending=False)
    return p[p["MIN_RANK"]<=top_k].sort_values(["TEAM","MIN_RANK"])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--team_file", required=True)
    ap.add_argument("--player_file", required=True)
    ap.add_argument("--cutoff", required=True)
    ap.add_argument("--out_dir", required=True)
    args = ap.parse_args()
    out_dir = Path(args.out_dir); out_dir.mkdir(parents=True, exist_ok=True)

    team = load_team(Path(args.team_file), args.cutoff)
    player = load_player(Path(args.player_file), args.cutoff)

    ts = team_snapshot(team)
    ts.to_csv(out_dir/"TeamSnapshot.csv", index=False)

    tpi = rotation_proxy(player)
    tpi.to_csv(out_dir/"TeamPlayerIndex.csv", index=False)

    prs = player_rotation_snapshot(player)
    if not prs.empty:
        prs.to_csv(out_dir/"PlayerRotationSnapshot.csv", index=False)

    # optional last30d games
    if "DATE" in team.columns:
        cutoff_ts = pd.Timestamp(args.cutoff)
        last30 = team[team["DATE"] >= (cutoff_ts - pd.Timedelta(days=30))].copy()
        last30.to_csv(out_dir/"TeamGameLog_Last30D.csv", index=False)

    print("Wrote cache to", out_dir.resolve())

if __name__=="__main__":
    main()
