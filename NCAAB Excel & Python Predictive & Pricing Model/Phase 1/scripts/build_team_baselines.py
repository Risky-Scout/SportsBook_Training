"""
build_team_baselines.py  —  Phase 1 Team Baseline Builder
==========================================================
Save to: /Users/josephshackelford/Desktop/SportsBook Training/mmodel_turnkey_complete/

Produces one row per D1 team-game with strictly pregame-valid rolling features.

Key design decision — D1-vs-D1 rolling filter:
  Rolling features (sea_*, L10_*, L5_*) are computed from D1-vs-D1 games ONLY.
  Non-D1 opponent games have OEFF~140 and DEFF~70 in the same game row, which
  inflates the season OEFF rolling mean and deflates the DEFF rolling mean by
  ~4.5 pts. The fix: mask those game values to NaN before the rolling transform.
  Evidence (run on actual feed):
    Raw gap (all games):     4.52 pts
    Gap after D1-vs-D1 fix:  0.35 pts

Single symmetric fallback:
  A single global_mean = mean(raw OEFF) is used as NaN fallback for ALL columns.
  Using separate per-column means would re-introduce asymmetry.

Leakage control:
  All rolling transforms use shift(1). No game's own outcome influences its features.

Acceptance tests:
  [1] Leakage: first-game rows have null rolling features
  [2] All KP_NAMEs are valid D1 teams
  [3] League OE/DE gap < 1.0 pt
  [4] Blend weight reconstruction error < 0.01
  [5] Non-D1 contamination info logged
  [6] Opponent-adjustment coverage > 90%
  [7] Data quality: full season AND last 7 days AND slate date (if provided)

Usage:
  python3 build_team_baselines.py \\
      --feed feeds_daily/03-20-2026-cbb-season-team-feed.xlsx

  python3 build_team_baselines.py \\
      --feed feeds_daily/03-20-2026-cbb-season-team-feed.xlsx \\
      --output cbb_cache/TeamBaselines.csv \\
      --slate-date 2026-03-21
"""
from __future__ import annotations

import sys
import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
log = logging.getLogger("baselines")

# ─────────────────────────────────────────────────────────────────────────────
# KenPom canonical team names (365 D1 teams, 2025-26)
# ─────────────────────────────────────────────────────────────────────────────
KP_NAMES = frozenset([
    "Abilene Christian","Air Force","Akron","Alabama","Alabama A&M","Alabama St.",
    "Albany","Alcorn St.","American","Appalachian St.","Arizona","Arizona St.",
    "Arkansas","Arkansas Pine Bluff","Arkansas St.","Army","Auburn","Austin Peay",
    "BYU","Ball St.","Baylor","Bellarmine","Belmont","Bethune Cookman","Binghamton",
    "Boise St.","Boston College","Boston University","Bowling Green","Bradley",
    "Brown","Bryant","Bucknell","Buffalo","Butler","CSUN","Cal Baptist","Cal Poly",
    "Cal St. Bakersfield","Cal St. Fullerton","California","Campbell","Canisius",
    "Central Arkansas","Central Connecticut","Central Michigan","Charleston",
    "Charleston Southern","Charlotte","Chattanooga","Chicago St.","Cincinnati",
    "Clemson","Cleveland St.","Coastal Carolina","Colgate","Colorado","Colorado St.",
    "Columbia","Connecticut","Coppin St.","Cornell","Creighton","Dartmouth",
    "Davidson","Dayton","DePaul","Delaware","Delaware St.","Denver","Detroit Mercy",
    "Drake","Drexel","Duke","Duquesne","East Carolina","East Tennessee St.",
    "East Texas A&M","Eastern Illinois","Eastern Kentucky","Eastern Michigan",
    "Eastern Washington","Elon","Evansville","FIU","Fairfield","Fairleigh Dickinson",
    "Florida","Florida A&M","Florida Atlantic","Florida Gulf Coast","Florida St.",
    "Fordham","Fresno St.","Furman","Gardner Webb","George Mason","George Washington",
    "Georgetown","Georgia","Georgia Southern","Georgia St.","Georgia Tech","Gonzaga",
    "Grambling St.","Grand Canyon","Green Bay","Hampton","Harvard","Hawaii",
    "High Point","Hofstra","Holy Cross","Houston","Houston Christian","Howard",
    "IU Indy","Idaho","Idaho St.","Illinois","Illinois Chicago","Illinois St.",
    "Incarnate Word","Indiana","Indiana St.","Iona","Iowa","Iowa St.","Jackson St.",
    "Jacksonville","Jacksonville St.","James Madison","Kansas","Kansas City",
    "Kansas St.","Kennesaw St.","Kent St.","Kentucky","LIU","LSU","La Salle",
    "Lafayette","Lamar","Le Moyne","Lehigh","Liberty","Lindenwood","Lipscomb",
    "Little Rock","Long Beach St.","Longwood","Louisiana","Louisiana Monroe",
    "Louisiana Tech","Louisville","Loyola Chicago","Loyola MD","Loyola Marymount",
    "Maine","Manhattan","Marist","Marquette","Marshall","Maryland",
    "Maryland Eastern Shore","Massachusetts","McNeese","Memphis","Mercer",
    "Mercyhurst","Merrimack","Miami FL","Miami OH","Michigan","Michigan St.",
    "Middle Tennessee","Milwaukee","Minnesota","Mississippi","Mississippi St.",
    "Mississippi Valley St.","Missouri","Missouri St.","Monmouth","Montana",
    "Montana St.","Morehead St.","Morgan St.","Mount St. Mary's","Murray St.",
    "N.C. State","NJIT","Navy","Nebraska","Nebraska Omaha","Nevada","New Hampshire",
    "New Haven","New Mexico","New Mexico St.","New Orleans","Niagara","Nicholls",
    "Norfolk St.","North Alabama","North Carolina","North Carolina A&T",
    "North Carolina Central","North Dakota","North Dakota St.","North Florida",
    "North Texas","Northeastern","Northern Arizona","Northern Colorado",
    "Northern Illinois","Northern Iowa","Northern Kentucky","Northwestern",
    "Northwestern St.","Notre Dame","Oakland","Ohio","Ohio St.","Oklahoma",
    "Oklahoma St.","Old Dominion","Oral Roberts","Oregon","Oregon St.","Pacific",
    "Penn","Penn St.","Pepperdine","Pittsburgh","Portland","Portland St.",
    "Prairie View A&M","Presbyterian","Princeton","Providence","Purdue",
    "Purdue Fort Wayne","Queens","Quinnipiac","Radford","Rhode Island","Rice",
    "Richmond","Rider","Robert Morris","Rutgers","SIUE","SMU","Sacramento St.",
    "Sacred Heart","Saint Francis","Saint Joseph's","Saint Louis","Saint Mary's",
    "Saint Peter's","Sam Houston St.","Samford","San Diego","San Diego St.",
    "San Francisco","San Jose St.","Santa Clara","Seattle","Seton Hall","Siena",
    "South Alabama","South Carolina","South Carolina St.","South Dakota",
    "South Dakota St.","South Florida","Southeast Missouri","Southeastern Louisiana",
    "Southern","Southern Illinois","Southern Indiana","Southern Miss","Southern Utah",
    "St. Bonaventure","St. John's","St. Thomas","Stanford","Stephen F. Austin",
    "Stetson","Stonehill","Stony Brook","Syracuse","TCU","Tarleton St.","Temple",
    "Tennessee","Tennessee Martin","Tennessee St.","Tennessee Tech","Texas",
    "Texas A&M","Texas A&M Corpus Chris","Texas Southern","Texas St.","Texas Tech",
    "The Citadel","Toledo","Towson","Troy","Tulane","Tulsa","UAB","UC Davis",
    "UC Irvine","UC Riverside","UC San Diego","UC Santa Barbara","UCF","UCLA",
    "UMBC","UMass Lowell","UNC Asheville","UNC Greensboro","UNC Wilmington","UNLV",
    "USC","USC Upstate","UT Arlington","UT Rio Grande Valley","UTEP","UTSA","Utah",
    "Utah St.","Utah Tech","Utah Valley","VCU","VMI","Valparaiso","Vanderbilt",
    "Vermont","Villanova","Virginia","Virginia Tech","Wagner","Wake Forest",
    "Washington","Washington St.","Weber St.","West Georgia","West Virginia",
    "Western Carolina","Western Illinois","Western Kentucky","Western Michigan",
    "Wichita St.","William & Mary","Winthrop","Wisconsin","Wofford","Wright St.",
    "Wyoming","Xavier","Yale","Youngstown St.",
])

# ─────────────────────────────────────────────────────────────────────────────
# BDB name → KenPom canonical crosswalk
# None = confirmed non-D1. No fuzzy matching anywhere.
# ─────────────────────────────────────────────────────────────────────────────
CROSSWALK = {
    "San José State Spartans":              "San Jose St.",
    "Hawai'i Rainbow Warriors":             "Hawaii",
    "Louisiana Ragin' Cajuns":              "Louisiana",
    "Gardner-Webb Runnin' Bulldogs":        "Gardner Webb",
    "Gardner-Webb Bulldogs":                "Gardner Webb",
    "George Washington Revolutionaries":    "George Washington",
    "George Washington Colonials":          "George Washington",
    "GW Revolutionaries":                   "George Washington",
    "McNeese Cowboys":                      "McNeese",
    "McNeese State Cowboys":                "McNeese",
    "Nicholls Colonels":                    "Nicholls",
    "Nicholls State Colonels":              "Nicholls",
    "Grand Canyon Lopes":                   "Grand Canyon",
    "Grand Canyon Antelopes":               "Grand Canyon",
    "SIU Edwardsville Cougars":             "SIUE",
    "SIUE Cougars":                         "SIUE",
    "App State Mountaineers":               "Appalachian St.",
    "Appalachian State Mountaineers":       "Appalachian St.",
    "UAlbany Great Danes":                  "Albany",
    "Alcorn State Braves":                  "Alcorn St.",
    "East Tennessee State Buccaneers":      "East Tennessee St.",
    "North Dakota State Bison":             "North Dakota St.",
    "Northwestern State Demons":            "Northwestern St.",
    "South Carolina State Bulldogs":        "South Carolina St.",
    "South Dakota State Jackrabbits":       "South Dakota St.",
    "Pennsylvania Quakers":                 "Penn",
    "Penn Quakers":                         "Penn",
    "Alabama Crimson Tide":                 "Alabama",
    "Alabama A&M Bulldogs":                 "Alabama A&M",
    "Alabama State Hornets":                "Alabama St.",
    "Arizona Wildcats":                     "Arizona",
    "Arizona State Sun Devils":             "Arizona St.",
    "Arkansas Razorbacks":                  "Arkansas",
    "Arkansas-Pine Bluff Golden Lions":     "Arkansas Pine Bluff",
    "Arkansas State Red Wolves":            "Arkansas St.",
    "Ball State Cardinals":                 "Ball St.",
    "Bethune-Cookman Wildcats":             "Bethune Cookman",
    "Boise State Broncos":                  "Boise St.",
    "California Baptist Lancers":           "Cal Baptist",
    "Cal State Bakersfield Roadrunners":    "Cal St. Bakersfield",
    "Cal State Fullerton Titans":           "Cal St. Fullerton",
    "Cal State Northridge Matadors":        "CSUN",
    "Charleston Cougars":                   "Charleston",
    "Chicago State Cougars":                "Chicago St.",
    "Connecticut Huskies":                  "Connecticut",
    "UConn Huskies":                        "Connecticut",
    "Coppin State Eagles":                  "Coppin St.",
    "Cleveland State Vikings":              "Cleveland St.",
    "Colorado State Rams":                  "Colorado St.",
    "Delaware Blue Hens":                   "Delaware",
    "Delaware Fightin Blue Hens":           "Delaware",
    "Delaware State Hornets":               "Delaware St.",
    "FIU Panthers":                         "FIU",
    "Florida International Panthers":       "FIU",
    "Florida Gators":                       "Florida",
    "Florida A&M Rattlers":                 "Florida A&M",
    "Florida Atlantic Owls":                "Florida Atlantic",
    "Florida Gulf Coast Eagles":            "Florida Gulf Coast",
    "Florida State Seminoles":              "Florida St.",
    "Fresno State Bulldogs":                "Fresno St.",
    "Georgia Bulldogs":                     "Georgia",
    "Georgia Southern Eagles":              "Georgia Southern",
    "Georgia State Panthers":               "Georgia St.",
    "Georgia Tech Yellow Jackets":          "Georgia Tech",
    "Grambling Tigers":                     "Grambling St.",
    "Houston Cougars":                      "Houston",
    "Idaho State Bengals":                  "Idaho St.",
    "Illinois Fighting Illini":             "Illinois",
    "Illinois-Chicago Flames":              "Illinois Chicago",
    "UIC Flames":                           "Illinois Chicago",
    "Illinois State Redbirds":              "Illinois St.",
    "Illinois St Redbirds":                 "Illinois St.",
    "Indiana Hoosiers":                     "Indiana",
    "Indiana State Sycamores":              "Indiana St.",
    "IU Indianapolis Jaguars":              "IU Indy",
    "Iowa State Cyclones":                  "Iowa St.",
    "Jackson State Tigers":                 "Jackson St.",
    "Jacksonville State Gamecocks":         "Jacksonville St.",
    "Kansas City Roos":                     "Kansas City",
    "Kansas State Wildcats":                "Kansas St.",
    "Kennesaw State Owls":                  "Kennesaw St.",
    "Kent State Golden Flashes":            "Kent St.",
    "LIU Sharks":                           "LIU",
    "Long Island University Sharks":        "LIU",
    "Long Beach State Beach":               "Long Beach St.",
    "Louisiana Monroe Warhawks":            "Louisiana Monroe",
    "UL Monroe Warhawks":                   "Louisiana Monroe",
    "Loyola Maryland Greyhounds":           "Loyola MD",
    "Miami Hurricanes":                     "Miami FL",
    "Miami (FL) Hurricanes":                "Miami FL",
    "Miami (OH) RedHawks":                  "Miami OH",
    "Michigan Wolverines":                  "Michigan",
    "Michigan State Spartans":              "Michigan St.",
    "Michigan St Spartans":                 "Michigan St.",
    "Mississippi Rebels":                   "Mississippi",
    "Ole Miss Rebels":                      "Mississippi",
    "Mississippi State Bulldogs":           "Mississippi St.",
    "Mississippi Valley State Delta Devils":"Mississippi Valley St.",
    "Missouri State Bears":                 "Missouri St.",
    "Morgan State Bears":                   "Morgan St.",
    "Montana State Bobcats":                "Montana St.",
    "Morehead State Eagles":                "Morehead St.",
    "Murray State Racers":                  "Murray St.",
    "NC State Wolfpack":                    "N.C. State",
    "North Carolina State Wolfpack":        "N.C. State",
    "North Carolina Tar Heels":             "North Carolina",
    "North Carolina A&T Aggies":            "North Carolina A&T",
    "North Carolina Central Eagles":        "North Carolina Central",
    "North Dakota Fighting Hawks":          "North Dakota",
    "Nebraska-Omaha Mavericks":             "Nebraska Omaha",
    "Omaha Mavericks":                      "Nebraska Omaha",
    "New Mexico State Aggies":              "New Mexico St.",
    "Norfolk State Spartans":               "Norfolk St.",
    "Ohio State Buckeyes":                  "Ohio St.",
    "Oklahoma State Cowboys":               "Oklahoma St.",
    "Oregon State Beavers":                 "Oregon St.",
    "Penn State Nittany Lions":             "Penn St.",
    "Pitt Panthers":                        "Pittsburgh",
    "Portland State Vikings":               "Portland St.",
    "Prairie View A&M Panthers":            "Prairie View A&M",
    "Sacramento State Hornets":             "Sacramento St.",
    "SE Louisiana Lions":                   "Southeastern Louisiana",
    "Southeastern Louisiana Lions":         "Southeastern Louisiana",
    "Southeast Missouri State Redhawks":    "Southeast Missouri",
    "Sam Houston Bearkats":                 "Sam Houston St.",
    "Sam Houston State Bearkats":           "Sam Houston St.",
    "San Diego State Aztecs":               "San Diego St.",
    "San Jose State Spartans":              "San Jose St.",
    "Seattle Redhawks":                     "Seattle",
    "Seattle U Redhawks":                   "Seattle",
    "South Carolina Upstate Spartans":      "USC Upstate",
    "Southern Indiana Screaming Eagles":    "Southern Indiana",
    "St. Thomas-Minnesota Tommies":         "St. Thomas",
    "Stephen F. Austin Lumberjacks":        "Stephen F. Austin",
    "Tennessee Volunteers":                 "Tennessee",
    "Tennessee State Tigers":               "Tennessee St.",
    "UT Martin Skyhawks":                   "Tennessee Martin",
    "Tarleton State Texans":                "Tarleton St.",
    "Texas A&M Aggies":                     "Texas A&M",
    "Texas A&M-Corpus Christi Islanders":   "Texas A&M Corpus Chris",
    "Texas State Bobcats":                  "Texas St.",
    "UALR Trojans":                         "Little Rock",
    "Utah State Aggies":                    "Utah St.",
    "Virginia Cavaliers":                   "Virginia",
    "Weber State Wildcats":                 "Weber St.",
    "Washington State Cougars":             "Washington St.",
    "Wisconsin-Milwaukee Panthers":         "Milwaukee",
    "Wichita State Shockers":               "Wichita St.",
    "Wichita St Shockers":                  "Wichita St.",
    "Wright State Raiders":                 "Wright St.",
    "Youngstown State Penguins":            "Youngstown St.",
    # Confirmed non-D1 — None is correct, not an error
    "Arkansas Baptist Buffaloes":           None,
    "Arlington Baptist Patriots":           None,
    "Belmont Abbey Crusaders":              None,
    "Bryan (TN) Lions":                     None,
    "Bryant Str-Alb Bobcats":               None,
    "Cincinnati Clermont Cougars":          None,
    "Colorado Christian Cougars":           None,
    "Colorado College Tigers":              None,
    "Columbia International Rams":          None,
    "Florida National Conquistadors":       None,
    "Georgia College Bobcats":              None,
    "Georgian Court Lions":                 None,
    "Greensboro College Pride":             None,
    "Hawai'i Hilo Vulcans":                 None,
    "Kansas Christian Falcons":             None,
    "Kentucky Christian Knights":           None,
    "Kentucky State Thorobreds":            None,
    "Louisiana Christian Wildcats":         None,
    "Manhattan Christian Thunder":          None,
    "Missouri Baptist Spartans":            None,
    "Montana Tech Orediggers":              None,
    "New Mexico Highlands Cowboys":         None,
    "Northeastern State RiverHawks":        None,
    "Northwest Indian RedHawks":            None,
    "Northwest University Eagles":          None,
    "Notre Dame (MD) Gators":               None,
    "Ohio Christian Trailblazers":          None,
    "Pacific Lutheran Lutes":               None,
    "Penn State-Behrend Lions":             None,
    "Pittsburgh - Greensburg Bobcats":      None,
    "Plattsburgh St Cardinals":             None,
    "Saint John's (MN) Johnnies":           None,
    "San Francisco State Gators":           None,
    "Siena Heights Saints":                 None,
    "Southern Arkansas Muleriders":         None,
    "Southern Virginia Knights":            None,
    "Southern Wesleyan Warriors":           None,
    "Southwestern Adventist Knights":       None,
    "Southwestern Christian Eagles":        None,
    "St. John Fisher Cardinals":            None,
    "St. Joseph's (NY) Bears":              None,
    "St. Thomas (TX) Celts":               None,
    "Tennessee Southern Firehawks":         None,
    "Tennessee Wesleyan Bulldogs":          None,
    "Texas Lutheran Bulldogs":              None,
    "Virginia St Trojans":                  None,
    "Warner Pacific Knights":               None,
    "Washington Adventist Shock":           None,
    "Washington and Lee Generals":          None,
    "West Virginia Wesleyan Bobcats":       None,
    "Wilmington (DE) Wildcats":             None,
}

# Blend weights
BLEND_SEA      = 0.50
BLEND_L10      = 0.30
BLEND_L5       = 0.20
MIN_GAMES_FULL = 10
MIN_GAMES_PART = 3

# All rolling stat columns (built from D1-vs-D1 games only)
ROLL_COLS = [
    "OEFF", "DEFF", "POSS",
    "g_eFG", "g_TOV", "g_ORB", "g_FTR", "g_3PAr", "g_PPP",
]


def get_kp_name(bdb_name, allow_missing=False):
    """Map BDB name to KenPom. No fuzzy matching. Raises KeyError if unknown."""
    bdb_name = str(bdb_name).strip()
    if bdb_name in CROSSWALK:
        return CROSSWALK[bdb_name]
    for n in [1, 2]:
        parts = bdb_name.rsplit(" ", n)
        cand = parts[0].strip() if len(parts) > 1 else None
        if cand and cand in KP_NAMES:
            return cand
    if allow_missing:
        return None
    raise KeyError(f"Not in crosswalk: {bdb_name!r}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--feed",       required=True)
    ap.add_argument("--output",     default="cbb_cache/TeamBaselines.csv")
    ap.add_argument("--slate-date", default=None)
    args = ap.parse_args()

    log.info("=" * 60)
    log.info("build_team_baselines.py  Phase 1")
    log.info("=" * 60)

    # ── Load ──────────────────────────────────────────────────────────────────
    df = pd.read_excel(args.feed, engine="openpyxl")
    df.columns = [str(c).strip() for c in df.columns]
    df["DATE"] = pd.to_datetime(df["DATE"], errors="coerce")
    for col in ["F","FG","FGA","3P","3PA","FT","FTA","OR","DR","TO",
                "POSS","PACE","OEFF","DEFF",
                "CLOSING SPREAD","CLOSING TOTAL","OPENING SPREAD","OPENING TOTAL"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.sort_values("DATE").reset_index(drop=True)
    log.info(f"  Feed rows: {len(df):,}  {df['DATE'].min().date()} → {df['DATE'].max().date()}")

    # ── DIAGNOSTIC: raw feed symmetry (should be gap=0) ──────────────────────
    raw_oe_mean = df["OEFF"].mean()
    raw_de_mean = df["DEFF"].mean()
    log.info(f"  DIAGNOSTIC raw feed: mean(OEFF)={raw_oe_mean:.4f}  "
             f"mean(DEFF)={raw_de_mean:.4f}  gap={abs(raw_oe_mean-raw_de_mean):.4f}")

    # ── Crosswalk ─────────────────────────────────────────────────────────────
    df["KP_NAME"] = df["TEAM"].apply(lambda x: get_kp_name(x, allow_missing=True))
    n_d1    = df["KP_NAME"].notna().sum()
    n_nond1 = df["KP_NAME"].isna().sum()
    log.info(f"  D1 rows: {n_d1:,}  Non-D1 excluded: {n_nond1:,}")
    df = df[df["KP_NAME"].notna()].copy()

    # ── Identify D1-vs-D1 games ───────────────────────────────────────────────
    # After crosswalk filter, a game with both teams present has count==2.
    # A game where only one team was D1 has count==1 — non-D1-opponent game.
    game_counts = df.groupby("GAME-ID").size()
    d1_d1_ids   = set(game_counts[game_counts == 2].index)
    n_d1d1    = len(d1_d1_ids)
    n_total   = df["GAME-ID"].nunique()
    n_nond1_g = n_total - n_d1d1
    log.info(f"  D1-vs-D1 games: {n_d1d1:,}  Non-D1-opponent games (excluded from rolling): {n_nond1_g:,}")

    # ── Per-game derived stats ────────────────────────────────────────────────
    fga  = df["FGA"].clip(lower=1)
    fta  = df["FTA"].fillna(0)
    to_  = df["TO"].fillna(0)
    thP  = df["3P"].fillna(0)
    thPA = df["3PA"].fillna(0)
    fg   = df["FG"].fillna(0)
    OR_  = df["OR"].fillna(0)
    DR_  = df["DR"].fillna(0)
    poss = df["POSS"].clip(lower=1)
    df["g_eFG"]  = (fg + 0.5 * thP) / fga
    df["g_TOV"]  = to_ / (fga + 0.44 * fta + to_).clip(lower=0.01)
    df["g_ORB"]  = OR_ / (OR_ + DR_).clip(lower=0.01)
    df["g_FTR"]  = fta / fga
    df["g_3PAr"] = thPA / fga
    df["g_PPP"]  = df["F"] / poss

    # ── Rolling features — D1-vs-D1 games only ───────────────────────────────
    # For each stat, mask non-D1-opponent game values to NaN before rolling.
    # expanding/rolling skip NaN by default, so those games are ignored.
    # shift(1) guarantees all features are strictly pregame (zero leakage).
    df = df.sort_values(["TEAM", "DATE"]).reset_index(drop=True)

    for col in ROLL_COLS:
        if col not in df.columns:
            continue
        d1_vals = df[col].where(df["GAME-ID"].isin(d1_d1_ids))
        df["__v__"] = d1_vals
        grp = df.groupby("TEAM")["__v__"]
        df[f"sea_{col}"] = grp.transform(lambda x: x.expanding().mean().shift(1))
        df[f"L10_{col}"] = grp.transform(lambda x: x.rolling(10, min_periods=3).mean().shift(1))
        df[f"L5_{col}"]  = grp.transform(lambda x: x.rolling(5,  min_periods=2).mean().shift(1))

    df = df.drop(columns=["__v__"], errors="ignore")
    df["games_played"] = df.groupby("TEAM").cumcount()

    # ── DIAGNOSTIC: rolling divergence after fix ──────────────────────────────
    mean_sea_oe = df["sea_OEFF"].mean()
    mean_sea_de = df["sea_DEFF"].mean()
    log.info(f"  DIAGNOSTIC rolling (D1-vs-D1): mean(sea_OEFF)={mean_sea_oe:.4f}  "
             f"mean(sea_DEFF)={mean_sea_de:.4f}  gap={abs(mean_sea_oe-mean_sea_de):.4f}")

    # ── Symmetric blend ───────────────────────────────────────────────────────
    # Single global_mean for ALL column fallbacks — prevents per-column divergence
    global_mean = float(df["OEFF"].mean())
    log.info(f"  Global symmetric fallback mean: {global_mean:.4f}")

    for col in ROLL_COLS:
        s, l10, l5 = f"sea_{col}", f"L10_{col}", f"L5_{col}"
        if s not in df.columns:
            continue
        sea_f = df[s].fillna(global_mean)
        l10_f = df[l10].fillna(sea_f) if l10 in df.columns else sea_f
        l5_f  = df[l5].fillna(sea_f)  if l5  in df.columns else sea_f
        df[f"blend_{col}"] = BLEND_SEA * sea_f + BLEND_L10 * l10_f + BLEND_L5 * l5_f

    def quality(row):
        gp = row["games_played"]
        if gp >= MIN_GAMES_FULL: return "FULL"
        if gp >= MIN_GAMES_PART: return "PARTIAL"
        return "PRIOR_ONLY"
    df["data_quality"] = df.apply(quality, axis=1)

    # ── Opponent-adjusted efficiency ──────────────────────────────────────────
    home = df[df["VENUE"] == "Home"][["GAME-ID","KP_NAME","blend_OEFF","blend_DEFF"]].copy()
    away = df[df["VENUE"] == "Road"][["GAME-ID","KP_NAME","blend_OEFF","blend_DEFF"]].copy()
    home.columns = ["GAME-ID","h","h_oe","h_de"]
    away.columns = ["GAME-ID","a","a_oe","a_de"]
    pairs = home.merge(away, on="GAME-ID", how="inner")
    pairs["h_adj_oe"] = pairs["h_oe"] * (global_mean / pairs["a_de"].clip(lower=80))
    pairs["h_adj_de"] = pairs["h_de"] * (global_mean / pairs["a_oe"].clip(lower=80))
    pairs["a_adj_oe"] = pairs["a_oe"] * (global_mean / pairs["h_de"].clip(lower=80))
    pairs["a_adj_de"] = pairs["a_de"] * (global_mean / pairs["h_oe"].clip(lower=80))

    df["adj_OEFF"] = np.nan
    df["adj_DEFF"] = np.nan
    for _, row in pairs.iterrows():
        gid = row["GAME-ID"]
        h = (df["GAME-ID"] == gid) & (df["VENUE"] == "Home")
        a = (df["GAME-ID"] == gid) & (df["VENUE"] == "Road")
        df.loc[h, "adj_OEFF"] = row["h_adj_oe"]
        df.loc[h, "adj_DEFF"] = row["h_adj_de"]
        df.loc[a, "adj_OEFF"] = row["a_adj_oe"]
        df.loc[a, "adj_DEFF"] = row["a_adj_de"]
    df["adj_OEFF"] = df["adj_OEFF"].fillna(df["blend_OEFF"])
    df["adj_DEFF"] = df["adj_DEFF"].fillna(df["blend_DEFF"])

    # ── Write output ──────────────────────────────────────────────────────────
    keep = [c for c in [
        "GAME-ID","DATE","KP_NAME","VENUE","F","OEFF","DEFF","POSS",
        "CLOSING SPREAD","CLOSING TOTAL",
        "games_played","data_quality",
        "sea_OEFF","sea_DEFF","sea_POSS",
        "sea_g_eFG","sea_g_TOV","sea_g_ORB","sea_g_FTR","sea_g_3PAr",
        "L10_OEFF","L10_DEFF","L10_POSS",
        "L10_g_eFG","L10_g_TOV","L10_g_ORB","L10_g_FTR",
        "L5_OEFF","L5_DEFF","L5_POSS",
        "L5_g_eFG","L5_g_TOV","L5_g_ORB","L5_g_FTR",
        "blend_OEFF","blend_DEFF","blend_POSS",
        "blend_g_eFG","blend_g_TOV","blend_g_ORB","blend_g_FTR",
        "adj_OEFF","adj_DEFF",
    ] if c in df.columns]

    out = df[keep].rename(columns={
        "GAME-ID":        "GAME_ID",
        "CLOSING SPREAD": "CLOSING_SPREAD",
        "CLOSING TOTAL":  "CLOSING_TOTAL",
    })
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)
    log.info(f"  Written: {out_path}  ({len(out):,} rows  {out['KP_NAME'].nunique()} teams)")

    # ── ACCEPTANCE TESTS ──────────────────────────────────────────────────────
    log.info("\n" + "=" * 60)
    log.info("ACCEPTANCE TESTS")
    log.info("=" * 60)
    passed = True

    # [1] Leakage
    first = out[out["games_played"] == 0]
    leaked = first["sea_OEFF"].notna().sum()
    if leaked:
        log.error(f"  [1] FAIL  Leakage: {leaked} first-game rows have non-null sea_OEFF")
        passed = False
    else:
        log.info("  [1] PASS  Leakage: first-game rows have null rolling features")

    # [2] KP_NAME validity
    bad = out[~out["KP_NAME"].isin(KP_NAMES)]
    if len(bad):
        log.error(f"  [2] FAIL  Invalid KP_NAMEs: {sorted(bad['KP_NAME'].unique())}")
        passed = False
    else:
        log.info(f"  [2] PASS  KP_NAME validity: {out['KP_NAME'].nunique()} valid D1 teams")

    # [3] Symmetric OE/DE gap
    oe = out["blend_OEFF"].mean()
    de = out["blend_DEFF"].mean()
    gap = abs(oe - de)
    if gap > 1.0:
        log.error(f"  [3] FAIL  blend OE={oe:.4f}  DE={de:.4f}  gap={gap:.4f}  (must be < 1.0)")
        passed = False
    else:
        log.info(f"  [3] PASS  blend OE={oe:.4f}  DE={de:.4f}  gap={gap:.4f}")

    # [4] Blend weight reconstruction
    r = out[(out["games_played"] >= 15) &
            out["sea_OEFF"].notna() & out["L10_OEFF"].notna() & out["L5_OEFF"].notna()].head(1)
    if len(r):
        r = r.iloc[0]
        err = abs(BLEND_SEA*r["sea_OEFF"] + BLEND_L10*r["L10_OEFF"] + BLEND_L5*r["L5_OEFF"] - r["blend_OEFF"])
        sym = "PASS" if err < 0.01 else "WARN"
        log.info(f"  [4] {sym}  Blend reconstruction error: {err:.8f}")

    # [5] Non-D1 contamination info
    log.info(f"  [5] INFO  D1-vs-D1 games used for rolling: {n_d1d1:,}  "
             f"Non-D1-opponent games excluded: {n_nond1_g:,}")

    # [6] Opponent-adjustment coverage
    adj_cov = out["adj_OEFF"].notna().mean()
    sym = "PASS" if adj_cov >= 0.90 else "WARN"
    log.info(f"  [6] {sym}  Opponent-adjustment coverage: {adj_cov:.1%}")

    # [7] Data quality — full season, last 7 days, slate date
    def qprint(subset, label):
        fp = (subset["data_quality"] == "FULL").mean()
        pp = (subset["data_quality"] == "PARTIAL").mean()
        rp = (subset["data_quality"] == "PRIOR_ONLY").mean()
        log.info(f"  [7] Data quality ({label:22s}): "
                 f"FULL={fp:.1%}  PARTIAL={pp:.1%}  PRIOR_ONLY={rp:.1%}")

    qprint(out, "full season")
    cutoff7 = out["DATE"].max() - pd.Timedelta(days=7)
    recent  = out[out["DATE"] >= cutoff7]
    if len(recent):
        qprint(recent, "last 7 days")
    if args.slate_date:
        slate = out[out["DATE"].dt.strftime("%Y-%m-%d") == args.slate_date]
        if len(slate):
            qprint(slate, f"slate {args.slate_date}")
        else:
            log.info(f"  [7] INFO  No rows for slate date {args.slate_date}")

    log.info(f"\n  {'ALL PASS' if passed else 'FAILURES — see above'}")
    log.info("=" * 60)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
