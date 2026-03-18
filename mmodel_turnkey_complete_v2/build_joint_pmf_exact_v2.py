
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


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


def load_params(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def poisson_pmf_vec(mu: float, max_x: int) -> np.ndarray:
    x = np.arange(max_x + 1, dtype=float)
    if mu <= 0:
        out = np.zeros(max_x + 1)
        out[0] = 1.0
        return out
    logp = -mu + x * np.log(mu) - np.array([math.lgamma(v + 1.0) for v in x])
    p = np.exp(logp)
    return p / p.sum()


def nb2_pmf_vec(mu: float, phi: float, max_x: int) -> np.ndarray:
    if mu <= 0:
        out = np.zeros(max_x + 1)
        out[0] = 1.0
        return out
    if phi <= 1e-12:
        return poisson_pmf_vec(mu, max_x)

    r = 1.0 / phi
    p = r / (r + mu)
    x = np.arange(max_x + 1, dtype=float)
    log_coeff = np.array([math.lgamma(v + r) - math.lgamma(r) - math.lgamma(v + 1.0) for v in x])
    logp = log_coeff + r * math.log(p) + x * math.log(1.0 - p)
    out = np.exp(logp)
    s = out.sum()
    if s <= 0 or not np.isfinite(s):
        return poisson_pmf_vec(mu, max_x)
    return out / s


def american_from_prob(p: float):
    if p <= 0.0 or p >= 1.0:
        return None
    if p >= 0.99:
        return -5000.0
    if p <= 0.01:
        return 5000.0
    if p >= 0.5:
        return round(-100.0 * p / (1.0 - p), 0)
    return round(100.0 * (1.0 - p) / p, 0)


def discrete_normal_states(n_states: int, sigma: float) -> tuple[np.ndarray, np.ndarray]:
    z = np.linspace(-2.5, 2.5, n_states)
    w = np.exp(-0.5 * z * z)
    w = w / w.sum()
    m = np.exp(sigma * z)
    m = m / np.sum(w * m)
    return m, w


def build_team_lookup(blended: pd.DataFrame) -> dict:
    lookup = {}
    for _, r in blended.iterrows():
        row = r.to_dict()
        name = str(row["TEAM"]).strip()
        lookup[name] = row
        lookup[_norm_team(name)] = row
    return lookup


def get_team_row(team: str, lookup: dict) -> dict:
    if team in lookup:
        return lookup[team]
    key = _norm_team(team)
    if key in lookup:
        return lookup[key]
    raise KeyError(f"Team not found in BlendedRatings: {team}")


@dataclass
class GameModel:
    cutoff: str
    home_team: str
    away_team: str
    site: str
    market_home_line: float
    market_total: float
    exp_tempo: float
    exp_home_ortg: float
    exp_away_ortg: float
    exp_home_pts: float
    exp_away_pts: float
    fair_home_margin: float
    fair_total: float


def build_game_model(game_row: pd.Series, team_lookup: dict, league: dict, params: dict) -> GameModel:
    home = get_team_row(game_row["Home Team"], team_lookup)
    away = get_team_row(game_row["Away Team"], team_lookup)

    th = float(home["BLEND_TEMPO"])
    ta = float(away["BLEND_TEMPO"])
    oe_h = float(home["BLEND_ADJ_OE"])
    de_h = float(home["BLEND_ADJ_DE"])
    oe_a = float(away["BLEND_ADJ_OE"])
    de_a = float(away["BLEND_ADJ_DE"])

    oe_bar = float(league["avg_oe"])
    de_bar = float(league["avg_de"])
    t_bar = float(league["avg_tempo"])

    site_flag = str(game_row["Site"]).strip().upper()
    site_adj = float(params["site_adj_ortg"]) if site_flag in {"H", "HOME"} else 0.0
    if site_flag in {"A", "AWAY"}:
        site_adj = -float(params["site_adj_ortg"])

    hrot = float(game_row.get("Home rotation ΔValue", 0.0) or 0.0)
    arot = float(game_row.get("Away rotation ΔValue", 0.0) or 0.0)
    hpadj = float(game_row.get("Home player ORtg adj (optional)", 0.0) or 0.0)
    apadj = float(game_row.get("Away player ORtg adj (optional)", 0.0) or 0.0)
    htadj = float(game_row.get("Home tempo adj (optional)", 0.0) or 0.0)
    atadj = float(game_row.get("Away tempo adj (optional)", 0.0) or 0.0)

    harmonic = 2.0 / (1.0 / th + 1.0 / ta)
    exp_tempo = (
        float(params["tempo_harmonic_weight"]) * harmonic
        + float(params["tempo_league_weight"]) * t_bar
        + htadj + atadj
    )

    rot_coeff = float(params["rot_delta_coeff_ortg"])
    exp_home_ortg = (
        oe_bar
        + 0.55 * (oe_h - oe_bar)
        + 0.45 * (de_a - de_bar)
        + site_adj
        + rot_coeff * (hrot - arot)
        + hpadj
    )
    exp_away_ortg = (
        oe_bar
        + 0.55 * (oe_a - oe_bar)
        + 0.45 * (de_h - de_bar)
        - site_adj
        + rot_coeff * (arot - hrot)
        + apadj
    )

    exp_home_pts = exp_tempo * exp_home_ortg / 100.0
    exp_away_pts = exp_tempo * exp_away_ortg / 100.0

    return GameModel(
        cutoff=str(game_row["Cutoff"]),
        home_team=str(game_row["Home Team"]),
        away_team=str(game_row["Away Team"]),
        site=str(game_row["Site"]),
        market_home_line=float(game_row["Home spread line (input)"]),
        market_total=float(game_row["Game total line (input)"]),
        exp_tempo=exp_tempo,
        exp_home_ortg=exp_home_ortg,
        exp_away_ortg=exp_away_ortg,
        exp_home_pts=exp_home_pts,
        exp_away_pts=exp_away_pts,
        fair_home_margin=exp_home_pts - exp_away_pts,
        fair_total=exp_home_pts + exp_away_pts,
    )


def build_joint_grid(game: GameModel, params: dict):
    phi_h = float(params["home_nb_dispersion"])
    phi_a = float(params["away_nb_dispersion"])
    shared_sigma = float(params["shared_tempo_sigma"])
    n_states = int(params["shared_tempo_states"])

    var_h = game.exp_home_pts + phi_h * game.exp_home_pts * game.exp_home_pts
    var_a = game.exp_away_pts + phi_a * game.exp_away_pts * game.exp_away_pts

    max_points = int(
        min(
            params["max_points_cap"],
            math.ceil(
                max(
                    game.exp_home_pts + 6.0 * math.sqrt(max(var_h, 1.0)),
                    game.exp_away_pts + 6.0 * math.sqrt(max(var_a, 1.0)),
                ) + params["max_points_buffer"]
            ),
        )
    )
    max_points = max(max_points, 110)

    multipliers, weights = discrete_normal_states(n_states, shared_sigma)
    xs = np.arange(max_points + 1)
    ys = np.arange(max_points + 1)
    grid = np.zeros((max_points + 1, max_points + 1), dtype=float)

    for m, w in zip(multipliers, weights):
        ph = nb2_pmf_vec(game.exp_home_pts * m, phi_h, max_points)
        pa = nb2_pmf_vec(game.exp_away_pts * m, phi_a, max_points)
        grid += w * np.outer(ph, pa)

    grid = grid / grid.sum()
    return xs, ys, grid


def summarize_grid(game: GameModel, xs: np.ndarray, ys: np.ndarray, grid: np.ndarray):
    max_x = len(xs) - 1
    max_y = len(ys) - 1

    margin_offset = max_y
    margin_vals = np.arange(-max_y, max_x + 1)
    margin_pmf = np.zeros(len(margin_vals), dtype=float)
    total_vals = np.arange(0, max_x + max_y + 1)
    total_pmf = np.zeros(len(total_vals), dtype=float)

    for i, x in enumerate(xs):
        row = grid[i, :]
        margins = int(x) - ys.astype(int)
        totals = int(x) + ys.astype(int)
        np.add.at(margin_pmf, margins + margin_offset, row)
        np.add.at(total_pmf, totals, row)

    home_win = float(margin_pmf[margin_vals > 0].sum())
    home_cover = float(margin_pmf[margin_vals > (-game.market_home_line)].sum())
    over_prob = float(total_pmf[total_vals > game.market_total].sum())

    summary = {
        "Cutoff": game.cutoff,
        "Home Team": game.home_team,
        "Away Team": game.away_team,
        "Site": game.site,
        "Market Home Line": game.market_home_line,
        "Market Total": game.market_total,
        "Expected Tempo": game.exp_tempo,
        "Expected Home ORtg": game.exp_home_ortg,
        "Expected Away ORtg": game.exp_away_ortg,
        "Expected Home Points": game.exp_home_pts,
        "Expected Away Points": game.exp_away_pts,
        "Fair Home Margin": game.fair_home_margin,
        "Fair Total": game.fair_total,
        "Exact Home Win Prob": home_win,
        "Exact Home Cover Prob": home_cover,
        "Exact Over Prob": over_prob,
        "Fair Home ML Decimal": (1.0 / home_win) if 0 < home_win < 1 else np.nan,
        "Fair Home Cover Decimal": (1.0 / home_cover) if 0 < home_cover < 1 else np.nan,
        "Fair Over Decimal": (1.0 / over_prob) if 0 < over_prob < 1 else np.nan,
        "Fair Home ML American": american_from_prob(home_win),
        "Fair Home Cover American": american_from_prob(home_cover),
        "Fair Over American": american_from_prob(over_prob),
    }

    margin_df = pd.DataFrame({
        "Cutoff": game.cutoff,
        "Home Team": game.home_team,
        "Away Team": game.away_team,
        "Margin": margin_vals,
        "PMF": margin_pmf,
    })
    total_df = pd.DataFrame({
        "Cutoff": game.cutoff,
        "Home Team": game.home_team,
        "Away Team": game.away_team,
        "Total": total_vals,
        "PMF": total_pmf,
    })

    grid_df = (
        pd.DataFrame(grid, index=xs, columns=ys)
        .rename_axis("Home Points")
        .reset_index()
        .melt(id_vars=["Home Points"], var_name="Away Points", value_name="Joint PMF")
    )
    grid_df.insert(0, "Away Team", game.away_team)
    grid_df.insert(0, "Home Team", game.home_team)
    grid_df.insert(0, "Cutoff", game.cutoff)
    return margin_df, total_df, grid_df, summary


def main():
    ap = argparse.ArgumentParser(description="Phase 2 exact joint score PMF builder (parallel path, no overwrite).")
    ap.add_argument("--gameinputs", required=True)
    ap.add_argument("--blended", required=True)
    ap.add_argument("--params", required=True)
    ap.add_argument("--out_dir", required=True)
    ap.add_argument("--cutoff", default=None)
    args = ap.parse_args()

    gi = pd.read_csv(args.gameinputs)
    br = pd.read_csv(args.blended)
    params = load_params(Path(args.params))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "grids").mkdir(parents=True, exist_ok=True)

    if args.cutoff:
        gi = gi[gi["Cutoff"].astype(str) == str(args.cutoff)].copy()

    lookup = build_team_lookup(br)
    league = {
        "avg_oe": float(pd.to_numeric(br["BLEND_ADJ_OE"], errors="coerce").mean()),
        "avg_de": float(pd.to_numeric(br["BLEND_ADJ_DE"], errors="coerce").mean()),
        "avg_tempo": float(pd.to_numeric(br["BLEND_TEMPO"], errors="coerce").mean()),
    }

    summaries = []
    margin_frames = []
    total_frames = []

    for _, row in gi.iterrows():
        game = build_game_model(row, lookup, league, params)
        xs, ys, grid = build_joint_grid(game, params)
        margin_df, total_df, grid_df, summary = summarize_grid(game, xs, ys, grid)
        summaries.append(summary)
        margin_frames.append(margin_df)
        total_frames.append(total_df)

        slug = re.sub(r"[^A-Za-z0-9]+", "_", f"{game.cutoff}_{game.away_team}_at_{game.home_team}").strip("_")
        grid_df.to_csv(out_dir / "grids" / f"exact_score_grid_{slug}.csv", index=False)

    summary_df = pd.DataFrame(summaries)
    margin_all = pd.concat(margin_frames, ignore_index=True) if margin_frames else pd.DataFrame()
    total_all = pd.concat(total_frames, ignore_index=True) if total_frames else pd.DataFrame()

    cutoff_tag = args.cutoff if args.cutoff else "ALL"
    summary_df.to_csv(out_dir / f"exact_pmf_game_summary_{cutoff_tag}.csv", index=False)
    margin_all.to_csv(out_dir / f"exact_margin_pmf_{cutoff_tag}.csv", index=False)
    total_all.to_csv(out_dir / f"exact_total_pmf_{cutoff_tag}.csv", index=False)

    print(f"Wrote {out_dir / f'exact_pmf_game_summary_{cutoff_tag}.csv'}")
    print(f"Wrote {out_dir / f'exact_margin_pmf_{cutoff_tag}.csv'}")
    print(f"Wrote {out_dir / f'exact_total_pmf_{cutoff_tag}.csv'}")
    print(f"Wrote score grids into {out_dir / 'grids'}")


if __name__ == "__main__":
    main()
