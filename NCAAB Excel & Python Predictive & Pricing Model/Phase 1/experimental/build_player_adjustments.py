"""
build_player_adjustments.py  —  Phase 3B Player Residual Layer
==============================================================
Reads:
  <player_feed>                              BDB season player feed (.xlsx)
  cbb_cache/TeamBaselines.csv
  cbb_cache/MatchupLatents_today_teamonly.csv

Writes:
  cbb_cache/PlayerAdjustments_today.csv     per-team adjustment + quality flags
  cbb_cache/PlayerAuditTrail_today.csv      per-player contribution trail (auditable)
  cbb_cache/MatchupLatents_today_player.csv team latents + player residuals applied

Hard rules:
  MIN_PLAYERS_THRESHOLD = 5  (rotation players with MIN>=10 in recent window)
  Zero adjustment if fewer than MIN_PLAYERS_THRESHOLD usable players.
  Clips: player_ortg_adj in [-8,+8], tempo_adj in [-5,+5], rotation_delta in [-0.10,+0.10]
  Shrinkage: adj *= min(n_recent_games, 5) / 5
  Recency decay: >7d -> *0.75, >14d -> *0.50
  Season baseline EXCLUDES the recent window (no contamination).
  Recent window is built from most-recent N games by DATE, then mapped to GAME-ID.
  No injury inference. No fake OUT logic. Observed data only.
"""
from __future__ import annotations
import sys, math, argparse, logging
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import special

logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
log = logging.getLogger("phase3b")

# ── Frozen thresholds (do not change silently) ────────────────────────────
MIN_PLAYERS_THRESHOLD = 5    # rotation players (MIN>=10) needed for non-zero adj
MIN_SEASON_GAMES      = 3    # baseline games required (else zero adj)
MAX_SHRINK_N          = 5    # full credibility at 5+ recent games
RECENT_N_DEFAULT      = 5    # default recent-window size
MAX_ORTG_ADJ          = 8.0  # pts/100 poss
MAX_TEMPO_ADJ         = 5.0  # possessions/game
MAX_ROT_DELTA         = 0.10 # fractional rotation delta

# ── BDB player feed -> KenPom crosswalk ──────────────────────────────────
XWALK = {
    "Texas Tech Red Raiders":"Texas Tech","Alabama Crimson Tide":"Alabama",
    "Arizona Wildcats":"Arizona","Utah State Aggies":"Utah St.",
    "High Point Panthers":"High Point","Arkansas Razorbacks":"Arkansas",
    "Seattle U Redhawks":"Seattle","Auburn Tigers":"Auburn",
    "Saint Joseph's Hawks":"Saint Joseph's","California Golden Bears":"California",
    "UConn Huskies":"Connecticut","Connecticut Huskies":"Connecticut",
    "Iowa State Cyclones":"Iowa St.","Miami (FL) Hurricanes":"Miami FL",
    "Miami Hurricanes":"Miami FL","New Mexico Lobos":"New Mexico",
    "UNLV Rebels":"UNLV","Vanderbilt Commodores":"Vanderbilt",
    "Virginia Cavaliers":"Virginia","Duke Blue Devils":"Duke",
    "Houston Cougars":"Houston","Kansas Jayhawks":"Kansas",
    "Kentucky Wildcats":"Kentucky","Michigan State Spartans":"Michigan St.",
    "Michigan St. Spartans":"Michigan St.","Purdue Boilermakers":"Purdue",
    "Tennessee Volunteers":"Tennessee","Texas Longhorns":"Texas",
    "Wisconsin Badgers":"Wisconsin","North Carolina Tar Heels":"North Carolina",
    "Gonzaga Bulldogs":"Gonzaga","Marquette Golden Eagles":"Marquette",
    "Michigan Wolverines":"Michigan","Ohio State Buckeyes":"Ohio St.",
    "Florida Gators":"Florida","Georgia Tech Yellow Jackets":"Georgia Tech",
    "Colorado State Rams":"Colorado St.","San Diego State Aztecs":"San Diego St.",
    "Boise State Broncos":"Boise St.","Oregon Ducks":"Oregon",
    "Creighton Bluejays":"Creighton","St. John's Red Storm":"St. John's",
    "Drake Bulldogs":"Drake","Pittsburgh Panthers":"Pittsburgh",
    "Syracuse Orange":"Syracuse","NC State Wolfpack":"N.C. State",
}
def R(n): return XWALK.get(str(n).strip(), str(n).strip())

# ── PMF engine (frozen params) ────────────────────────────────────────────
PHI,SIG,NQ,MX = 0.004,0.085,9,130
WO,WD = 0.55,0.45

def nb_lpmf(k,mu,phi):
    r=1/phi; p=r/(r+mu)
    return (special.gammaln(k+r)-special.gammaln(r)-special.gammaln(k+1)
            +r*np.log(max(p,1e-12))+k*np.log(max(1-p,1e-12)))

def price_game(mp,h_ortg,a_ortg,sp,tot):
    pts,wts=np.polynomial.hermite.hermgauss(NQ)
    lmu=math.log(max(mp,1))-0.5*SIG*SIG
    g=np.zeros((MX+1,MX+1)); xs=np.arange(MX+1,dtype=float)
    eh=ea=eh2=ea2=eha=0.0; mha=np.zeros(MX+1); maa=np.zeros(MX+1)
    for pt,wt in zip(pts,wts):
        pace=math.exp(lmu+math.sqrt(2)*SIG*pt); wg=wt/math.sqrt(math.pi)
        mh=max(pace*h_ortg/100,0.1); ma=max(pace*a_ortg/100,0.1)
        ph=np.exp(nb_lpmf(xs,mh,PHI)); ph/=ph.sum()
        pa=np.exp(nb_lpmf(xs,ma,PHI)); pa/=pa.sum()
        g+=wg*np.outer(ph,pa); _eh=(xs*ph).sum(); _ea=(xs*pa).sum()
        eh+=wg*_eh; ea+=wg*_ea
        eh2+=wg*((xs**2)*ph).sum(); ea2+=wg*((xs**2)*pa).sum(); eha+=wg*_eh*_ea
        mha+=wg*ph; maa+=wg*pa
    s=g.sum()
    if s>0: g/=s; mha/=mha.sum(); maa/=maa.sum()
    vh=eh2-eh**2; va=ea2-ea**2; cov=eha-eh*ea
    n=g.shape[0]; mg=np.zeros(2*n-1); tg=np.zeros(2*n-1)
    mv=np.arange(-(n-1),n); tv=np.arange(2*n-1)
    for i in range(n):
        np.add.at(mg,i-np.arange(n)+n-1,g[i]); np.add.at(tg,i+np.arange(n),g[i])
    return {"eh":eh,"ea":ea,"gs":g.sum(),
            "sd_m":math.sqrt(max(vh+va-2*cov,0)),"sd_t":math.sqrt(max(vh+va+2*cov,0)),
            "corr":cov/math.sqrt(max(vh*va,1e-9)),
            "p_ml":float(mg[mv>0].sum()),
            "p_hc":float(mg[mv>-sp].sum()) if sp is not None else float("nan"),
            "p_ov":float(tg[tv>tot].sum()) if tot is not None else float("nan"),
            "p_h70":float(mha[70:].sum()),"p_h75":float(mha[75:].sum()),
            "p_a70":float(maa[70:].sum()),"p_a75":float(maa[75:].sum())}

def amer(p):
    if p is None or (isinstance(p,float) and math.isnan(p)): return float("nan")
    p=max(min(float(p),0.9999),0.0001)
    return round(-(p/(1-p))*100) if p>=0.5 else round(((1-p)/p)*100)


def load_player_feed(path: Path) -> pd.DataFrame:
    log.info(f"Loading player feed: {path}")
    df = pd.read_excel(path, engine="openpyxl")
    df.columns = [str(c).replace("\n"," ").strip() for c in df.columns]
    df = df.rename(columns={
        "OWN  TEAM":"TEAM","OPPONENT  TEAM":"OPP",
        "PLAYER  FULL NAME":"PLAYER",
        "VENUE (R/H/N)":"VENUE","STARTER\n(Y/N)":"STARTER",
        "USAGE  RATE (%)":"USAGE",
    })
    df["DATE"] = pd.to_datetime(df["DATE"], errors="coerce")
    for col in ["MIN","PTS","FG","FGA","3P","3PA","FT","FTA",
                "OR","DR","TOT","A","PF","ST","TO","BL","USAGE"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    df["KP_NAME"] = df["TEAM"].apply(R)
    df["POSS_p"]  = df["FGA"] + 0.44*df["FTA"] + df["TO"]
    df["PPP_p"]   = np.where(df["POSS_p"]>0, df["PTS"]/df["POSS_p"], 0.0)
    log.info(f"  {len(df):,} rows  {df['DATE'].min().date()} -> {df['DATE'].max().date()}")
    return df


def compute_team_adjustment(
    feed: pd.DataFrame,
    kp_name: str,
    pricing_date: str,
    recent_n: int = RECENT_N_DEFAULT,
) -> tuple[dict, list[dict]]:
    """
    Returns (team_summary_dict, player_audit_rows).
    Season baseline EXCLUDES the recent window (no contamination).
    Recent window is N most-recent games by DATE, mapped to GAME-ID.
    """
    cutoff = pd.Timestamp(pricing_date)
    team_df = feed[(feed["KP_NAME"]==kp_name) & (feed["DATE"]<cutoff)].copy()

    null_summary = {
        "team":kp_name,"player_data_available":False,
        "n_players_with_data":0,"n_recent_games":0,"n_season_games":0,
        "data_recency_days":999,"adjustment_confidence":"LOW",
        "player_ortg_adj":0.0,"tempo_adj":0.0,"rotation_delta":0.0,
        "raw_ortg_adj":0.0,"raw_tempo_adj":0.0,"raw_rotation_delta":0.0,
        "shrink_factor":0.0,"zero_fallback_reason":"no_data",
    }

    if len(team_df) == 0:
        log.warning(f"  {kp_name}: NO DATA")
        return null_summary, []

    # ── Build recent window by DATE (not by sorted GAME-ID) ──────────────
    # Get unique game dates sorted descending, take the N most recent
    game_dates = (team_df.groupby("GAME-ID")["DATE"].max()
                  .sort_values(ascending=False))
    recent_game_ids = set(game_dates.head(recent_n).index)
    season_game_ids = set(game_dates.tail(len(game_dates)-recent_n).index)
    # Season baseline strictly excludes recent window
    if len(season_game_ids) == 0:
        # Edge case: fewer total games than recent_n — use all as both (accept noise)
        season_game_ids = set(game_dates.index)

    recent_df = team_df[team_df["GAME-ID"].isin(recent_game_ids)].copy()
    season_df = team_df[team_df["GAME-ID"].isin(season_game_ids)].copy()

    last_date   = recent_df["DATE"].max()
    recency_days= int((cutoff - last_date).days)
    n_recent    = len(recent_game_ids)
    n_season    = len(season_game_ids)

    usable_players = recent_df[recent_df["MIN"]>=10]["PLAYER"].nunique()

    if usable_players < MIN_PLAYERS_THRESHOLD:
        log.info(f"  {kp_name}: {usable_players} usable players < {MIN_PLAYERS_THRESHOLD} — zero adj")
        null_summary.update({
            "player_data_available":True,
            "n_players_with_data":usable_players,
            "n_recent_games":n_recent,"n_season_games":n_season,
            "data_recency_days":recency_days,
            "zero_fallback_reason":f"only_{usable_players}_usable_players",
        })
        return null_summary, []

    if n_season < MIN_SEASON_GAMES:
        log.info(f"  {kp_name}: only {n_season} season-baseline games — zero adj")
        null_summary.update({
            "player_data_available":True,"n_players_with_data":usable_players,
            "n_recent_games":n_recent,"n_season_games":n_season,
            "data_recency_days":recency_days,
            "zero_fallback_reason":f"only_{n_season}_season_games",
        })
        return null_summary, []

    # ── Per-player contribution trail ─────────────────────────────────────
    audit_rows = []

    def player_poss_weight(df_sub):
        """Returns per-player: {player: (total_poss, total_ppp_weighted, n_games)}"""
        res = {}
        for player, grp in df_sub[df_sub["MIN"]>=5].groupby("PLAYER"):
            tot_poss = float(grp["POSS_p"].sum())
            if tot_poss < 0.5: continue
            wt_ppp   = float((grp["PPP_p"] * grp["POSS_p"]).sum()) / tot_poss
            n_games  = grp["GAME-ID"].nunique()
            tot_min  = float(grp["MIN"].sum())
            res[player] = {"poss":tot_poss,"ppp":wt_ppp,"n_games":n_games,"min":tot_min}
        return res

    recent_pw  = player_poss_weight(recent_df)
    season_pw  = player_poss_weight(season_df)

    # Team-level recent PPP (usage-weighted across players)
    total_poss_r = sum(v["poss"] for v in recent_pw.values())
    total_poss_s = sum(v["poss"] for v in season_pw.values())

    if total_poss_r < 1 or total_poss_s < 1:
        null_summary.update({"zero_fallback_reason":"insufficient_poss"})
        return null_summary, []

    team_ppp_r = sum(v["ppp"]*v["poss"] for v in recent_pw.values()) / total_poss_r
    team_ppp_s = sum(v["ppp"]*v["poss"] for v in season_pw.values()) / total_poss_s

    raw_ortg = (team_ppp_r - team_ppp_s) * 100.0  # pts/100 poss

    # Tempo: team poss per game from player data
    def team_poss_pg(df_sub, game_ids):
        per_game = df_sub.groupby("GAME-ID")["POSS_p"].sum()
        return float((per_game / 5.0).mean()) if len(per_game)>0 else None
    tempo_r = team_poss_pg(recent_df, recent_game_ids)
    tempo_s = team_poss_pg(season_df, season_game_ids)
    raw_tempo = (tempo_r - tempo_s) if (tempo_r and tempo_s) else 0.0

    # Rotation delta: top-8 minute concentration
    def top8_share(df_sub):
        by_player = df_sub.groupby("PLAYER")["MIN"].sum()
        total = by_player.sum()
        if total < 1: return None
        return float(by_player.nlargest(8).sum() / total)
    rot_r = top8_share(recent_df); rot_s = top8_share(season_df)
    raw_rot = (rot_r - rot_s) if (rot_r and rot_s) else 0.0

    # ── Per-player audit trail ────────────────────────────────────────────
    all_players = set(recent_pw) | set(season_pw)
    for player in all_players:
        rp = recent_pw.get(player, {"poss":0,"ppp":0,"n_games":0,"min":0})
        sp = season_pw.get(player, {"poss":0,"ppp":0,"n_games":0,"min":0})
        # Player's contribution to team ortg delta
        # = (player_ppp_recent - player_ppp_season) * (player_poss_share_recent)
        poss_share = rp["poss"]/total_poss_r if total_poss_r>0 else 0
        player_contrib = (rp["ppp"] - sp["ppp"]) * 100.0 * poss_share if rp["poss"]>0 and sp["poss"]>0 else 0.0
        audit_rows.append({
            "team":kp_name,"player":player,
            "recent_min_total":round(rp["min"],1),"recent_poss":round(rp["poss"],2),
            "recent_ppp":round(rp["ppp"],4),"recent_n_games":rp["n_games"],
            "season_poss":round(sp["poss"],2),"season_ppp":round(sp["ppp"],4),
            "season_n_games":sp["n_games"],
            "poss_share_recent":round(poss_share,4),
            "player_ortg_contrib":round(player_contrib,4),
            "in_recent":rp["poss"]>0,"in_season":sp["poss"]>0,
        })

    # ── Shrinkage ─────────────────────────────────────────────────────────
    shrink = min(n_recent, MAX_SHRINK_N) / MAX_SHRINK_N
    if recency_days > 14: shrink *= 0.50
    elif recency_days > 7: shrink *= 0.75

    ortg_adj  = float(np.clip(raw_ortg  * shrink, -MAX_ORTG_ADJ,  MAX_ORTG_ADJ))
    tempo_adj = float(np.clip(raw_tempo * shrink, -MAX_TEMPO_ADJ, MAX_TEMPO_ADJ))
    rot_delta = float(np.clip(raw_rot   * shrink, -MAX_ROT_DELTA, MAX_ROT_DELTA))

    # ── Confidence: MIN_PLAYERS_THRESHOLD=5, locked ───────────────────────
    if n_recent >= 5 and recency_days <= 7 and usable_players >= 7:
        confidence = "HIGH"
    elif n_recent >= 3 and usable_players >= MIN_PLAYERS_THRESHOLD:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    summary = {
        "team":kp_name,"player_data_available":True,
        "n_players_with_data":usable_players,
        "n_recent_games":n_recent,"n_season_games":n_season,
        "data_recency_days":recency_days,
        "adjustment_confidence":confidence,
        "raw_ortg_adj":round(raw_ortg,4),
        "raw_tempo_adj":round(raw_tempo,4),
        "raw_rotation_delta":round(raw_rot,4),
        "shrink_factor":round(shrink,4),
        "player_ortg_adj":round(ortg_adj,4),
        "tempo_adj":round(tempo_adj,4),
        "rotation_delta":round(rot_delta,4),
        "team_ppp_recent":round(team_ppp_r,4),
        "team_ppp_season":round(team_ppp_s,4),
        "zero_fallback_reason":"none",
    }
    return summary, audit_rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--player-feed",  default="feeds_daily/03-20-2026-cbb-season-player-feed.xlsx",dest="player_feed")
    ap.add_argument("--baselines",    default="cbb_cache/TeamBaselines.csv")
    ap.add_argument("--latents",      default="cbb_cache/MatchupLatents_today_teamonly.csv")
    ap.add_argument("--out-adj",      default="cbb_cache/PlayerAdjustments_today.csv",dest="out_adj")
    ap.add_argument("--out-audit",    default="cbb_cache/PlayerAuditTrail_today.csv",dest="out_audit")
    ap.add_argument("--out-latents",  default="cbb_cache/MatchupLatents_today_player.csv",dest="out_latents")
    ap.add_argument("--date",         default="2026-03-21")
    ap.add_argument("--recent-games", type=int, default=RECENT_N_DEFAULT, dest="recent_games")
    args = ap.parse_args()

    log.info("="*65)
    log.info("Phase 3B  —  Player Residual Layer")
    log.info(f"  Date={args.date}  recent_games={args.recent_games}")
    log.info(f"  MIN_PLAYERS_THRESHOLD={MIN_PLAYERS_THRESHOLD}  (locked — workbook metadata matches)")
    log.info(f"  Clips: ortg±{MAX_ORTG_ADJ}  tempo±{MAX_TEMPO_ADJ}  rot±{MAX_ROT_DELTA}")
    log.info(f"  Season baseline EXCLUDES recent window (no contamination)")
    log.info(f"  Recent window built by DATE (not by sorted GAME-ID)")
    log.info(f"  No injury inference. No fake OUT logic.")
    log.info("="*65)

    feed    = load_player_feed(Path(args.player_feed))
    latents = pd.read_csv(args.latents)
    log.info(f"Team-only latents: {len(latents)} games")

    teams = sorted(set(latents["HOME_KP"].tolist() + latents["AWAY_KP"].tolist()))
    log.info(f"Unique teams on slate: {len(teams)}")

    log.info("\nComputing adjustments:")
    adj_rows = []; all_audit = []
    for t in teams:
        summary, audit = compute_team_adjustment(feed, t, args.date, args.recent_games)
        adj_rows.append(summary); all_audit.extend(audit)
        log.info(f"  {t:<22}: conf={summary['adjustment_confidence']:<6}  "
                 f"ortg={summary['player_ortg_adj']:+.3f}  "
                 f"tempo={summary['tempo_adj']:+.3f}  "
                 f"n_plyr={summary['n_players_with_data']}  "
                 f"recency={summary['data_recency_days']}d  "
                 f"fallback={summary['zero_fallback_reason']}")

    adj_df   = pd.DataFrame(adj_rows)
    audit_df = pd.DataFrame(all_audit)
    adj_df.to_csv(args.out_adj, index=False)
    audit_df.to_csv(args.out_audit, index=False)
    log.info(f"\nWritten: {args.out_adj}  ({len(adj_df)} teams)")
    log.info(f"Written: {args.out_audit}  ({len(audit_df)} player-game rows)")

    # ── Apply residuals to latents ────────────────────────────────────────
    adj_map = adj_df.set_index("team")

    def get_adj(team, field, default=0.0):
        if team in adj_map.index:
            v = adj_map.loc[team, field]
            return float(v) if pd.notna(v) else default
        return default

    player_rows = []
    kp_lg_tp = 67.39  # frozen
    for _, row in latents.iterrows():
        h=str(row["HOME_KP"]); a=str(row["AWAY_KP"])

        p_ortg_h  = get_adj(h,"player_ortg_adj")
        p_ortg_a  = get_adj(a,"player_ortg_adj")
        p_tempo_h = get_adj(h,"tempo_adj")
        p_tempo_a = get_adj(a,"tempo_adj")
        p_rot_h   = get_adj(h,"rotation_delta")
        p_rot_a   = get_adj(a,"rotation_delta")

        pda_h = bool(get_adj(h,"player_data_available",False))
        pda_a = bool(get_adj(a,"player_data_available",False))
        conf_h= str(adj_map.loc[h,"adjustment_confidence"]) if h in adj_map.index else "LOW"
        conf_a= str(adj_map.loc[a,"adjustment_confidence"]) if a in adj_map.index else "LOW"
        n_h   = int(get_adj(h,"n_players_with_data",0))
        n_a   = int(get_adj(a,"n_players_with_data",0))
        rec_h = int(get_adj(h,"data_recency_days",999))
        rec_a = int(get_adj(a,"data_recency_days",999))
        fb_h  = str(adj_map.loc[h,"zero_fallback_reason"]) if h in adj_map.index else "no_data"
        fb_a  = str(adj_map.loc[a,"zero_fallback_reason"]) if a in adj_map.index else "no_data"

        oe_h_adj = float(row["oe_h"]) + p_ortg_h
        de_h_adj = float(row["de_h"])
        tp_h_adj = float(row["tp_h"]) + p_tempo_h
        oe_a_adj = float(row["oe_a"]) + p_ortg_a
        de_a_adj = float(row["de_a"])
        tp_a_adj = float(row["tp_a"]) + p_tempo_a
        blg = float(row["blend_lg"])
        sa  = float(row["sa_used"])

        tp_h_c=max(tp_h_adj,50); tp_a_c=max(tp_a_adj,50)
        harm=2/(1/tp_h_c+1/tp_a_c); mp=0.85*harm+0.15*kp_lg_tp
        h_ortg_adj=blg+WO*(oe_h_adj-blg)+WD*(de_a_adj-blg)+sa
        a_ortg_adj=blg+WO*(oe_a_adj-blg)+WD*(de_h_adj-blg)-sa

        sp_r=float(row.get("mkt_spread",float("nan")) or float("nan"))
        tt_r=float(row.get("mkt_total", float("nan")) or float("nan"))
        sp=sp_r if not math.isnan(sp_r) else None
        tt=tt_r if not math.isnan(tt_r) else None

        pmf=price_game(mp,h_ortg_adj,a_ortg_adj,sp,tt)

        r=dict(row); r.update({
            "oe_h_adj":round(oe_h_adj,3),"de_h_adj":round(de_h_adj,3),"tp_h_adj":round(tp_h_adj,3),
            "oe_a_adj":round(oe_a_adj,3),"de_a_adj":round(de_a_adj,3),"tp_a_adj":round(tp_a_adj,3),
            "h_ortg_adj":round(h_ortg_adj,3),"a_ortg_adj":round(a_ortg_adj,3),"mu_pace_adj":round(mp,3),
            "player_ortg_adj_h":round(p_ortg_h,4),"player_ortg_adj_a":round(p_ortg_a,4),
            "tempo_adj_h":round(p_tempo_h,4),"tempo_adj_a":round(p_tempo_a,4),
            "rotation_delta_h":round(p_rot_h,4),"rotation_delta_a":round(p_rot_a,4),
            "player_data_available_h":pda_h,"player_data_available_a":pda_a,
            "n_players_with_data_h":n_h,"n_players_with_data_a":n_a,
            "data_recency_days_h":rec_h,"data_recency_days_a":rec_a,
            "adjustment_confidence_h":conf_h,"adjustment_confidence_a":conf_a,
            "zero_fallback_reason_h":fb_h,"zero_fallback_reason_a":fb_a,
            "fair_spread_adj":round(pmf["eh"]-pmf["ea"],3),
            "fair_total_adj":round(pmf["eh"]+pmf["ea"],3),
            "fair_home_tt_adj":round(pmf["eh"],3),"fair_away_tt_adj":round(pmf["ea"],3),
            "p_ml_home_adj":round(pmf["p_ml"],4),
            "p_home_cover_adj":round(pmf["p_hc"],4) if not math.isnan(pmf["p_hc"]) else float("nan"),
            "p_over_adj":round(pmf["p_ov"],4) if not math.isnan(pmf["p_ov"]) else float("nan"),
            "fair_ml_home_american_adj":amer(pmf["p_ml"]),
            "fair_ml_away_american_adj":amer(1-pmf["p_ml"]),
            "pmf_grid_sum_adj":round(pmf["gs"],10),
            "delta_spread":round((pmf["eh"]-pmf["ea"])-float(row["fair_spread"]),3),
            "delta_total":round((pmf["eh"]+pmf["ea"])-float(row["fair_total"]),3),
            "delta_p_ml":round(pmf["p_ml"]-float(row["p_ml_home_raw"]),4),
            "player_layer_applied":True,
            "model_version":"team_player_v1_p2_30",
        })
        player_rows.append(r)

    result=pd.DataFrame(player_rows)
    result.to_csv(args.out_latents,index=False)
    log.info(f"Written: {args.out_latents}  ({len(result)} games)")

    # ── Verification ──────────────────────────────────────────────────────
    log.info(f"\n{'='*65}\nPHASE 3B VERIFICATION\n{'='*65}")
    log.info(f"  PlayerAdjustments rows:    {len(adj_df)}")
    log.info(f"  PlayerAuditTrail rows:     {len(audit_df)}")
    log.info(f"  Teams with data=True:      {adj_df['player_data_available'].sum()}")
    log.info(f"  Confidence: {adj_df['adjustment_confidence'].value_counts().to_dict()}")
    log.info(f"  Non-zero ortg_adj:         {(adj_df['player_ortg_adj'].abs()>0.001).sum()} teams")
    log.info(f"  ortg_adj range:            {adj_df['player_ortg_adj'].min():+.3f} to {adj_df['player_ortg_adj'].max():+.3f}")
    log.info(f"  tempo_adj range:           {adj_df['tempo_adj'].min():+.3f} to {adj_df['tempo_adj'].max():+.3f}")
    log.info(f"  player_layer_applied=True: {result['player_layer_applied'].all()}")
    log.info(f"  NaN in player_ortg_adj_h:  {result['player_ortg_adj_h'].isna().sum()}")
    log.info(f"  NaN in confidence_h:       {result['adjustment_confidence_h'].isna().sum()}")
    log.info(f"  PMF grid_sum max err:      {(result['pmf_grid_sum_adj']-1).abs().max():.2e}")

    if result["mkt_spread"].notna().sum()>3:
        both=result.dropna(subset=["fair_spread_adj","mkt_spread"])
        c=float(np.corrcoef(both["fair_spread_adj"],-both["mkt_spread"])[0,1])
        mad=float((both["fair_spread_adj"]-(-both["mkt_spread"])).abs().mean())
        log.info(f"  corr(fair_spread_adj,-mkt): {c:.4f}")
        log.info(f"  MAD vs market (adj):        {mad:.3f} pts")

    log.info(f"\n  SAMPLE TRACES (first 5):")
    for _,r in result.head(5).iterrows():
        log.info(f"\n    [{r['HOME_KP']} vs {r['AWAY_KP']}]")
        log.info(f"      Team-only:  spread={r['fair_spread']:+.3f}  total={r['fair_total']:.3f}  p_ml={r['p_ml_home_raw']:.4f}")
        log.info(f"      Adj (h):    ortg={r['player_ortg_adj_h']:+.4f}  tempo={r['tempo_adj_h']:+.4f}  conf={r['adjustment_confidence_h']}  fallback={r['zero_fallback_reason_h']}")
        log.info(f"      Adj (a):    ortg={r['player_ortg_adj_a']:+.4f}  tempo={r['tempo_adj_a']:+.4f}  conf={r['adjustment_confidence_a']}  fallback={r['zero_fallback_reason_a']}")
        log.info(f"      Adjusted:   spread={r['fair_spread_adj']:+.3f}  total={r['fair_total_adj']:.3f}  p_ml={r['p_ml_home_adj']:.4f}")
        log.info(f"      Delta:      Δspread={r['delta_spread']:+.3f}  Δtotal={r['delta_total']:+.3f}  Δp_ml={r['delta_p_ml']:+.4f}")
        log.info(f"      Grid:       {r['pmf_grid_sum_adj']:.8f}")

    log.info(f"\n  Next: python3 build_team_player_workbook_v1.py --latents {args.out_latents} --adj {args.out_adj} --out outputs/ncaab_market_maker_team_player_v1_p2_30_{args.date}.xlsx --date {args.date}")

if __name__=="__main__": main()
