#!/usr/bin/env python3
"""
Enhanced build_game_inputs.py for the market-maker workflow.

Key upgrades:
- canonicalizes schedule team names against BlendedRatings team names
- uses a three-part pace/efficiency blend:
    60% KenPom adjusted
    25% season raw team feed
    15% recent / last-10 raw team feed
- preserves FanMatch predictive fields from Schedule.csv when present:
    HomePred, VisitorPred, HomeWP, PredTempo, ThrillScore, GameID, ranks, Line Source
- writes expanded GameInputs.csv with those sanity-check fields available to Excel

Output columns in GameInputs.csv:
A  Cutoff
B  Home Team
C  Away Team
D  Site
E  Home spread line (input)
F  Game total line (input)
G  Home rotation ΔValue
H  Away rotation ΔValue
I  Home player ORtg adj (optional)
J  Away player ORtg adj (optional)
K  Home tempo adj (optional)
L  Away tempo adj (optional)
M  FanMatch HomePred
N  FanMatch AwayPred
O  FanMatch HomeWP
P  FanMatch PredTempo
Q  ThrillScore
R  Line Source
S  GameID
T  HomeRank
U  VisitorRank
"""
from __future__ import annotations
import argparse, re
from pathlib import Path
import numpy as np
import pandas as pd

OVERRIDES = {
    "Iowa State Cyclones": "Iowa St.",
    "Kent State Golden Flashes": "Kent St.",
    "Ohio State Buckeyes": "Ohio St.",
    "Prairie View Panthers": "Prairie View A&M",
    "Saint Joseph's Hawks": "Saint Joseph's",
    "GW Revolutionaries": "George Washington",
    "St. Bonaventure Bonnies": "St. Bonaventure",
    "St. John's Red Storm": "St. John's",
    "Hawai'i Rainbow Warriors": "Hawaii",
    "Southern Prairie View Panthers": "Prairie View A&M",
}

def _norm_team(s: str) -> str:
    if s is None:
        return ""
    s = str(s).strip().lower()
    s = s.replace("&", "and")
    s = re.sub(r"[’'`\.]", "", s)
    s = re.sub(r"[^a-z0-9\s\-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"^st\s+", "saint ", s)
    s = re.sub(r"^st-", "saint ", s)
    return s

def _match_key(s: str) -> str:
    s = _norm_team(s)
    s = re.sub(r"\bstate\b", "st", s)
    s = s.replace("saint ", "st ")
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s

def _require(df: pd.DataFrame, cols: list[str], label: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise KeyError(f"{label}: missing required columns {missing}. Found sample: {list(df.columns)[:40]}")

def _load_kp(cache_dir: Path, season: int) -> pd.DataFrame:
    p = cache_dir / f"KenPom_Ratings_{season}.csv"
    if not p.exists():
        raise FileNotFoundError(f"Missing {p}. Run kenpom_pull.py first.")
    kp = pd.read_csv(p)
    _require(kp, ["TeamName", "AdjOE", "AdjDE", "AdjTempo"], str(p))
    out = pd.DataFrame({
        "TEAM": kp["TeamName"].astype(str).str.strip(),
        "TEAM_KEY": kp["TeamName"].astype(str).str.strip().map(_norm_team),
        "KP_ADJ_OE": pd.to_numeric(kp["AdjOE"], errors="coerce"),
        "KP_ADJ_DE": pd.to_numeric(kp["AdjDE"], errors="coerce"),
        "KP_ADJ_TEMPO": pd.to_numeric(kp["AdjTempo"], errors="coerce"),
        "KP_SOS": pd.to_numeric(kp["SOS"], errors="coerce") if "SOS" in kp.columns else np.nan,
        "KP_CONF": kp["ConfShort"].astype(str).str.strip() if "ConfShort" in kp.columns else "",
        "KP_TEAMID": pd.to_numeric(kp["TeamID"], errors="coerce") if "TeamID" in kp.columns else np.nan,
    })
    return out

def _load_team_snapshot(cache_dir: Path) -> pd.DataFrame:
    p = cache_dir / "TeamSnapshot.csv"
    if not p.exists():
        raise FileNotFoundError(f"Missing {p}. Run build_cbb_cache.py first.")
    df = pd.read_csv(p)
    if "TEAM" not in df.columns:
        raise KeyError(f"{p}: expected TEAM column. Found sample: {list(df.columns)[:40]}")
    df["TEAM"] = df["TEAM"].astype(str).str.strip()
    df["TEAM_KEY"] = df["TEAM"].map(_norm_team)
    for c in ["OEFF", "DEFF", "PACE", "L10_OEFF", "L10_DEFF", "L10_PACE"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

def _load_tpi(cache_dir: Path) -> pd.DataFrame:
    p = cache_dir / "TeamPlayerIndex.csv"
    if not p.exists():
        raise FileNotFoundError(f"Missing {p}. Run build_cbb_cache.py first.")
    df = pd.read_csv(p)
    if "TEAM" not in df.columns:
        raise KeyError(f"{p}: expected TEAM column. Found sample: {list(df.columns)[:40]}")
    df["TEAM"] = df["TEAM"].astype(str).str.strip()
    df["TEAM_KEY"] = df["TEAM"].map(_norm_team)
    if "ROT_DELTA_VALUE" not in df.columns:
        df["ROT_DELTA_VALUE"] = 0.0
    df["ROT_DELTA_VALUE"] = pd.to_numeric(df["ROT_DELTA_VALUE"], errors="coerce").fillna(0.0)
    return df[["TEAM_KEY", "ROT_DELTA_VALUE"]]

def _load_schedule(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing schedule file: {path}")
    sch = pd.read_csv(path)
    req = ["Cutoff", "Home Team", "Away Team", "Site", "Home spread line (input)", "Game total line (input)"]
    _require(sch, req, str(path))
    return sch

def _canonicalize_schedule_teams(sch: pd.DataFrame, valid_team_names: pd.Series) -> pd.DataFrame:
    valid = pd.Series(valid_team_names).dropna().astype(str).str.strip()
    valid_set = set(valid)
    key_to_team = {_match_key(t): t for t in valid}
    def canon(name: str) -> str:
        name = str(name).strip()
        if name in valid_set:
            return name
        if name in OVERRIDES and OVERRIDES[name] in valid_set:
            return OVERRIDES[name]
        mk = _match_key(name)
        if mk in key_to_team:
            return key_to_team[mk]
        return name
    sch = sch.copy()
    sch["Home Team"] = sch["Home Team"].astype(str).map(canon)
    sch["Away Team"] = sch["Away Team"].astype(str).map(canon)
    sch["HOME_KEY"] = sch["Home Team"].map(_norm_team)
    sch["AWAY_KEY"] = sch["Away Team"].map(_norm_team)
    return sch

def build_blended_ratings(kp: pd.DataFrame, snap: pd.DataFrame) -> pd.DataFrame:
    merged = kp.merge(
        snap[["TEAM_KEY","OEFF","DEFF","PACE","L10_OEFF","L10_DEFF","L10_PACE"]],
        on="TEAM_KEY", how="left"
    )
    merged["SEASON_OE"] = pd.to_numeric(merged["OEFF"], errors="coerce")
    merged["SEASON_DE"] = pd.to_numeric(merged["DEFF"], errors="coerce")
    merged["SEASON_TEMPO"] = pd.to_numeric(merged["PACE"], errors="coerce")
    merged["RECENT_OE"] = pd.to_numeric(merged["L10_OEFF"], errors="coerce")
    merged["RECENT_DE"] = pd.to_numeric(merged["L10_DEFF"], errors="coerce")
    merged["RECENT_TEMPO"] = pd.to_numeric(merged["L10_PACE"], errors="coerce")
    # weights: 60% KP adj, 25% season feed, 15% recent feed
    for kp_col, seas_col, rec_col, out_col in [
        ("KP_ADJ_OE","SEASON_OE","RECENT_OE","BLEND_ADJ_OE"),
        ("KP_ADJ_DE","SEASON_DE","RECENT_DE","BLEND_ADJ_DE"),
        ("KP_ADJ_TEMPO","SEASON_TEMPO","RECENT_TEMPO","BLEND_TEMPO"),
    ]:
        base = merged[kp_col]
        seas = merged[seas_col]
        rec = merged[rec_col]
        val = 0.60 * base
        denom = 0.60
        val = np.where(seas.notna(), val + 0.25 * seas, val)
        denom = np.where(seas.notna(), denom + 0.25, denom)
        val = np.where(rec.notna(), val + 0.15 * rec, val)
        denom = np.where(rec.notna(), denom + 0.15, denom)
        merged[out_col] = np.where(denom > 0, val / denom, base)
    out = merged[[
        "TEAM","TEAM_KEY","KP_CONF","KP_TEAMID","KP_SOS",
        "KP_ADJ_OE","KP_ADJ_DE","KP_ADJ_TEMPO",
        "SEASON_OE","SEASON_DE","SEASON_TEMPO",
        "RECENT_OE","RECENT_DE","RECENT_TEMPO",
        "BLEND_ADJ_OE","BLEND_ADJ_DE","BLEND_TEMPO"
    ]].copy()
    out["BLEND_ADJ_EM"] = out["BLEND_ADJ_OE"] - out["BLEND_ADJ_DE"]
    return out

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache_dir", required=True)
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--schedule", required=True)
    ap.add_argument("--out_dir", required=True)
    args = ap.parse_args()

    cache_dir = Path(args.cache_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    kp = _load_kp(cache_dir, args.season)
    snap = _load_team_snapshot(cache_dir)
    tpi = _load_tpi(cache_dir)
    sch = _load_schedule(Path(args.schedule))

    blended = build_blended_ratings(kp, snap)
    blended.to_csv(out_dir / "BlendedRatings.csv", index=False)

    sch = _canonicalize_schedule_teams(sch, blended["TEAM"])

    # Attach rotation deltas to schedule
    tpi_home = tpi.rename(columns={"TEAM_KEY": "HOME_KEY", "ROT_DELTA_VALUE": "Home rotation ΔValue"})
    tpi_away = tpi.rename(columns={"TEAM_KEY": "AWAY_KEY", "ROT_DELTA_VALUE": "Away rotation ΔValue"})
    game = sch.merge(tpi_home, on="HOME_KEY", how="left").merge(tpi_away, on="AWAY_KEY", how="left")
    game["Home rotation ΔValue"] = game["Home rotation ΔValue"].fillna(0.0)
    game["Away rotation ΔValue"] = game["Away rotation ΔValue"].fillna(0.0)

    # Optional manual adjustments (default 0)
    game["Home player ORtg adj (optional)"] = 0.0
    game["Away player ORtg adj (optional)"] = 0.0
    game["Home tempo adj (optional)"] = 0.0
    game["Away tempo adj (optional)"] = 0.0

    # Preserve sanity-check / fanmatch fields when present
    extras = [
        "HomePred","VisitorPred","HomeWP","PredTempo","ThrillScore","Line Source",
        "GameID","HomeRank","VisitorRank"
    ]
    for c in extras:
        if c not in game.columns:
            game[c] = np.nan if c not in ("Line Source",) else ""

    game_out = game[[
        "Cutoff","Home Team","Away Team","Site","Home spread line (input)","Game total line (input)",
        "Home rotation ΔValue","Away rotation ΔValue",
        "Home player ORtg adj (optional)","Away player ORtg adj (optional)",
        "Home tempo adj (optional)","Away tempo adj (optional)",
        "HomePred","VisitorPred","HomeWP","PredTempo","ThrillScore","Line Source","GameID","HomeRank","VisitorRank"
    ]].copy()
    game_out = game_out.rename(columns={
        "HomePred":"FanMatch HomePred",
        "VisitorPred":"FanMatch AwayPred",
        "HomeWP":"FanMatch HomeWP",
        "PredTempo":"FanMatch PredTempo",
        "Line Source":"Market Line Source"
    })
    game_out.to_csv(out_dir / "GameInputs.csv", index=False)

    print(f"Wrote: {out_dir / 'BlendedRatings.csv'}")
    print(f"Wrote: {out_dir / 'GameInputs.csv'}")

if __name__ == "__main__":
    main()
