#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd


COMBINED_SHEET_CANDIDATES = ["Odds_from_Odds_Api", "odds_from_Odds_API"]
TOTAL_SHEET_CANDIDATES = ["Odds_from_Odds_Api_Total", "odds_from_Odds_API_Total"]
SPREAD_SHEET_CANDIDATES = ["Odds_from_Odds_Api_Spread", "odds_from_Odds_API_Spread"]

REQUIRED_MAP_SHEET = "Odds_Map_OddsToKP"

NUM_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


def parse_args():
    ap = argparse.ArgumentParser(
        description=(
            "Extract live odds from workbook tabs, map names via Odds_Map_OddsToKP, "
            "and build Schedule.csv for the pricing model."
        )
    )
    ap.add_argument("--workbook", required=True, help="Path to .xlsm/.xlsx workbook")
    ap.add_argument("--date", required=True, help="Target slate date YYYY-MM-DD")
    ap.add_argument("--out-schedule", default="Schedule.csv")
    ap.add_argument("--out-normalized", default=None)
    ap.add_argument("--spread-side", choices=["point1", "point2"], default="point1",
                    help="Which point column in the SPREAD sheet corresponds to the HOME team's spread")
    ap.add_argument("--consensus", choices=["median", "mean", "last"], default="median")
    ap.add_argument("--total-sheet", default=None,
                    help="Optional explicit totals tab name. Defaults to Odds_from_Odds_Api_Total.")
    ap.add_argument("--spread-sheet", default=None,
                    help="Optional explicit spreads tab name. Defaults to Odds_from_Odds_Api_Spread.")
    ap.add_argument("--combined-sheet", default=None,
                    help="Optional combined tab name if you still use one sheet with both markets.")
    return ap.parse_args()


def normalize_date(v) -> str:
    if v is None or v == "":
        return ""
    s = str(v).strip()
    if not s:
        return ""

    # Odds API commence values are UTC. Convert to ET so night games stay on the right slate date.
    try:
        ts = pd.to_datetime(s, utc=True, errors="raise")
        if pd.isna(ts):
            return ""
        return ts.tz_convert("America/New_York").strftime("%Y-%m-%d")
    except Exception:
        pass

    # Fallback for plain date / Excel-ish values
    try:
        ts = pd.to_datetime(s, errors="raise")
        if pd.isna(ts):
            return ""
        return ts.strftime("%Y-%m-%d")
    except Exception:
        return s[:10]


def parse_event_name(event: str) -> Tuple[Optional[str], Optional[str], str]:
    s = str(event).strip()
    if not s:
        return None, None, "H"
    # Common add-in export uses Away_Home
    if "_" in s and s.count("_") == 1:
        away, home = [x.strip() for x in s.split("_", 1)]
        return away, home, "H"
    for sep, site in [(" @ ", "H"), (" at ", "H"), (" vs. ", "N"), (" vs ", "N"), (" v ", "N")]:
        if sep in s:
            away, home = [x.strip() for x in s.split(sep, 1)]
            return away, home, site
    return None, None, "H"


def extract_first_number(txt) -> Optional[float]:
    if pd.isna(txt):
        return None
    m = NUM_RE.search(str(txt))
    return float(m.group()) if m else None


def detect_market_type_from_points(p1, p2) -> str:
    s1 = str(p1).lower()
    s2 = str(p2).lower()
    if "over" in s1 or "under" in s1 or "over" in s2 or "under" in s2:
        return "totals"
    n1 = extract_first_number(p1)
    n2 = extract_first_number(p2)
    if n1 is not None or n2 is not None:
        return "spreads"
    return "unknown"


def load_mapping(workbook: Path) -> dict[str, str]:
    m = pd.read_excel(workbook, sheet_name=REQUIRED_MAP_SHEET, engine="openpyxl")
    need = {"Odds API Name", "KenPom Name"}
    if not need.issubset(m.columns):
        raise ValueError(f"{REQUIRED_MAP_SHEET} is missing columns: {need - set(m.columns)}")
    m = m.dropna(subset=["Odds API Name", "KenPom Name"]).copy()
    m["Odds API Name"] = m["Odds API Name"].astype(str).str.strip()
    m["KenPom Name"] = m["KenPom Name"].astype(str).str.strip()
    return dict(zip(m["Odds API Name"], m["KenPom Name"]))


def choose_sheet_name(xls: pd.ExcelFile, explicit: Optional[str], candidates: list[str], label: str) -> Optional[str]:
    if explicit:
        if explicit not in xls.sheet_names:
            raise ValueError(f"{label} sheet '{explicit}' not found. Available: {xls.sheet_names}")
        return explicit
    for name in candidates:
        if name in xls.sheet_names:
            return name
    return None


def load_sheet_if_present(xls: pd.ExcelFile, name: Optional[str]) -> Optional[pd.DataFrame]:
    if name is None:
        return None
    return pd.read_excel(xls, sheet_name=name, engine="openpyxl")



def standardize_columns(df: pd.DataFrame, sheet_name: str) -> pd.DataFrame:
    out = df.copy()

    def norm(x: str) -> str:
        x = str(x).strip().lower()
        x = x.replace("\ufeff", "").replace("\u200b", "")
        x = re.sub(r"[^a-z0-9]+", "_", x).strip("_")
        return x

    alias = {
        "event": "event_name",
        "event_name": "event_name",
        "matchup": "event_name",
        "game": "event_name",
        "game_name": "event_name",

        "commence": "commence",
        "commence_time": "commence",
        "start_time": "commence",
        "game_time": "commence",

        "status": "status",

        "book": "bookmaker",
        "bookmaker": "bookmaker",
        "sportsbook": "bookmaker",

        "last_update": "last_update",
        "last_updated": "last_update",
        "updated": "last_update",
        "update_time": "last_update",

        "point1": "point_1",
        "point_1": "point_1",
        "line1": "point_1",
        "line_1": "point_1",
        "over": "point_1",
        "total": "point_1",
        "point": "point_1",

        "point2": "point_2",
        "point_2": "point_2",
        "line2": "point_2",
        "line_2": "point_2",
        "under": "point_2",

        "odd1": "odd_1",
        "odd_1": "odd_1",
        "odds1": "odd_1",
        "odds_1": "odd_1",
        "price1": "odd_1",
        "price_1": "odd_1",
        "over_price": "odd_1",

        "odd2": "odd_2",
        "odd_2": "odd_2",
        "odds2": "odd_2",
        "odds_2": "odd_2",
        "price2": "odd_2",
        "price_2": "odd_2",
        "under_price": "odd_2",
    }

    renamed = {}
    for c in out.columns:
        k = norm(c)
        renamed[c] = alias.get(k, k)
    out = out.rename(columns=renamed)

    # collapse duplicate column names by taking first non-null left-to-right
    cols_unique = []
    collapsed = pd.DataFrame(index=out.index)
    for c in out.columns:
        if c in cols_unique:
            continue
        cols_unique.append(c)
        same = out.loc[:, [x for x in out.columns if x == c]]
        if same.shape[1] == 1:
            collapsed[c] = same.iloc[:, 0]
        else:
            collapsed[c] = same.bfill(axis=1).iloc[:, 0]
    out = collapsed

    # totals tabs may store strings like "over 144.0" / "under 144.0"
    sname = str(sheet_name).lower()
    if "total" in sname:
        if "point_1" in out.columns:
            out["point_1"] = pd.to_numeric(
                out["point_1"].astype(str).str.extract(r"(-?\d+(?:\.\d+)?)", expand=False),
                errors="coerce",
            )
        if "point_2" in out.columns:
            out["point_2"] = pd.to_numeric(
                out["point_2"].astype(str).str.extract(r"(-?\d+(?:\.\d+)?)", expand=False),
                errors="coerce",
            )
        if "point_1" in out.columns and "point_2" not in out.columns:
            out["point_2"] = out["point_1"]
        if "point_2" in out.columns and "point_1" not in out.columns:
            out["point_1"] = out["point_2"]

    # fill optional metadata if absent
    for c in ["commence", "status", "bookmaker", "last_update"]:
        if c not in out.columns:
            out[c] = pd.NA

    required = ["event_name", "point_1", "point_2", "odd_1", "odd_2"]
    missing = [c for c in required if c not in out.columns]
    if missing:
        raise ValueError(f"{sheet_name} is missing required columns: {missing}. Found: {list(out.columns)}")

    return out

def extract_totals_df(df: pd.DataFrame, target_date: str) -> pd.DataFrame:
    rows = []
    for _, r in df.iterrows():
        row_date = normalize_date(r["commence"])
        if row_date != target_date:
            continue
        away_odds, home_odds, site = parse_event_name(r["event_name"])
        if not away_odds or not home_odds:
            continue
        total_line = extract_first_number(r["point_1"])
        if total_line is None:
            total_line = extract_first_number(r["point_2"])
        if total_line is None:
            continue
        rows.append({
            "Cutoff": target_date,
            "Home Team Odds API": home_odds,
            "Away Team Odds API": away_odds,
            "Site": site,
            "Bookmaker": str(r["bookmaker"]).strip(),
            "Commence": r["commence"],
            "Book Last Update": r["last_update"],
            "Game total line (input)": float(total_line),
            "Over Price": r.get("odd_1", pd.NA),
            "Under Price": r.get("odd_2", pd.NA),
        })
    return pd.DataFrame(rows)


def extract_spreads_df(df: pd.DataFrame, target_date: str, spread_side: str) -> pd.DataFrame:
    rows = []
    for _, r in df.iterrows():
        row_date = normalize_date(r["commence"])
        if row_date != target_date:
            continue
        market_type = detect_market_type_from_points(r["point_1"], r["point_2"])
        if market_type != "spreads":
            continue
        away_odds, home_odds, site = parse_event_name(r["event_name"])
        if not away_odds or not home_odds:
            continue
        home_spread = extract_first_number(r["point_1"] if spread_side == "point1" else r["point_2"])
        if home_spread is None:
            continue
        rows.append({
            "Cutoff": target_date,
            "Home Team Odds API": home_odds,
            "Away Team Odds API": away_odds,
            "Site": site,
            "Bookmaker": str(r["bookmaker"]).strip(),
            "Commence": r["commence"],
            "Book Last Update": r["last_update"],
            "Home spread line (input)": float(home_spread),
            "Home Spread Price": r.get("odd_1" if spread_side == "point1" else "odd_2", pd.NA),
        })
    return pd.DataFrame(rows)


def apply_mapping(df: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    out["Home Team"] = out["Home Team Odds API"].map(mapping).fillna(out["Home Team Odds API"])
    out["Away Team"] = out["Away Team Odds API"].map(mapping).fillna(out["Away Team Odds API"])
    return out


def build_normalized_and_schedule(
    totals_df: pd.DataFrame,
    spreads_df: pd.DataFrame,
    consensus: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    key_cols = ["Cutoff", "Home Team", "Away Team", "Site", "Bookmaker"]
    if totals_df.empty or spreads_df.empty:
        raise RuntimeError(
            f"Need both totals and spreads. Found totals={len(totals_df)} rows, spreads={len(spreads_df)} rows."
        )

    merged = spreads_df.merge(
        totals_df[key_cols + ["Game total line (input)", "Over Price", "Under Price"]],
        on=key_cols,
        how="inner",
    )
    if merged.empty:
        raise RuntimeError(
            "No matching spread+total rows after merging by game/bookmaker/date. "
            "Make sure both tabs contain the same games/books for the chosen date."
        )

    merged = merged.sort_values(["Cutoff", "Home Team", "Away Team", "Bookmaker"]).reset_index(drop=True)

    sched_group = ["Cutoff", "Home Team", "Away Team", "Site"]
    if consensus == "median":
        sched = (
            merged.groupby(sched_group, as_index=False)
            .agg({
                "Home spread line (input)": "median",
                "Game total line (input)": "median",
            })
        )
    elif consensus == "mean":
        sched = (
            merged.groupby(sched_group, as_index=False)
            .agg({
                "Home spread line (input)": "mean",
                "Game total line (input)": "mean",
            })
        )
    else:
        # last updated bookmaker row wins
        merged["_book_last_ts"] = pd.to_datetime(merged["Book Last Update"], errors="coerce", utc=True)
        sched = (
            merged.sort_values(["_book_last_ts", "Bookmaker"], ascending=[False, True])
            .groupby(sched_group, as_index=False)
            .first()[sched_group + ["Home spread line (input)", "Game total line (input)"]]
        )
    sched["Home spread line (input)"] = pd.to_numeric(sched["Home spread line (input)"], errors="coerce").round(1)
    sched["Game total line (input)"] = pd.to_numeric(sched["Game total line (input)"], errors="coerce").round(1)
    sched = sched.sort_values(["Cutoff", "Home Team", "Away Team"]).reset_index(drop=True)
    return merged, sched


def main():
    args = parse_args()
    wb = Path(args.workbook)
    if not wb.exists():
        raise FileNotFoundError(f"Workbook not found: {wb}")

    mapping = load_mapping(wb)

    xls = pd.ExcelFile(wb, engine="openpyxl")
    total_sheet = choose_sheet_name(xls, args.total_sheet, TOTAL_SHEET_CANDIDATES, "Totals")
    spread_sheet = choose_sheet_name(xls, args.spread_sheet, SPREAD_SHEET_CANDIDATES, "Spreads")
    combined_sheet = choose_sheet_name(xls, args.combined_sheet, COMBINED_SHEET_CANDIDATES, "Combined")

    totals_raw = load_sheet_if_present(xls, total_sheet)
    spreads_raw = load_sheet_if_present(xls, spread_sheet)

    totals_std = standardize_columns(totals_raw, total_sheet) if totals_raw is not None else pd.DataFrame()
    spreads_std = standardize_columns(spreads_raw, spread_sheet) if spreads_raw is not None else pd.DataFrame()

    # fallback for old one-sheet design
    if (totals_std.empty or spreads_std.empty) and combined_sheet is not None:
        combined_raw = pd.read_excel(xls, sheet_name=combined_sheet, engine="openpyxl")
        combined_std = standardize_columns(combined_raw, combined_sheet)
        if totals_std.empty:
            totals_std = combined_std.copy()
        if spreads_std.empty:
            spreads_std = combined_std.copy()

    totals_extracted = extract_totals_df(totals_std, args.date)
    spreads_extracted = extract_spreads_df(spreads_std, args.date, args.spread_side)

    totals_mapped = apply_mapping(totals_extracted, mapping)
    spreads_mapped = apply_mapping(spreads_extracted, mapping)

    normalized, schedule = build_normalized_and_schedule(totals_mapped, spreads_mapped, args.consensus)

    out_schedule = Path(args.out_schedule)
    out_schedule.parent.mkdir(parents=True, exist_ok=True)
    schedule.to_csv(out_schedule, index=False)

    if args.out_normalized:
        out_norm = Path(args.out_normalized)
        out_norm.parent.mkdir(parents=True, exist_ok=True)
        normalized.to_csv(out_norm, index=False)

    print(f"Workbook: {wb}")
    print(f"Date: {args.date}")
    print(f"Totals tab used: {total_sheet or combined_sheet}")
    print(f"Spreads tab used: {spread_sheet or combined_sheet}")
    print(f"Totals rows found: {len(totals_mapped)}")
    print(f"Spreads rows found: {len(spreads_mapped)}")
    print(f"Normalized rows merged: {len(normalized)}")
    print(f"Schedule games written: {len(schedule)}")
    print()
    print(schedule.head(20).to_string(index=False))


if __name__ == "__main__":
    main()
