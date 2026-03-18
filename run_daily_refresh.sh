#!/usr/bin/env bash
set -euo pipefail

TEAM_FILE="${TEAM_FILE:-$(ls -1t feeds_daily/*-cbb-season-team-feed.xlsx 2>/dev/null | head -1)}"
PLAYER_FILE="${PLAYER_FILE:-$(ls -1t feeds_daily/*-cbb-season-player-feed.xlsx 2>/dev/null | head -1)}"

CACHE_DIR="./cbb_cache"
SEASON="2026"
CUTOFF="${CUTOFF:-$(basename "$TEAM_FILE" | awk -F- '{printf "%s-%s-%s",$3,$1,$2}')}"
SCHEDULE_CSV="./Schedule.csv"

: "${KPC_API_KEY:?Missing KPC_API_KEY env var}"
: "${KPC_BASE_URL:?Missing KPC_BASE_URL env var}"

mkdir -p "$CACHE_DIR" "./logs"
TS="$(date +"%Y%m%d_%H%M%S")"
LOG="./logs/refresh_${TS}.log"

echo "=== Daily refresh started: ${TS} ===" | tee -a "$LOG"
echo "CACHE_DIR=${CACHE_DIR}  SEASON=${SEASON}  CUTOFF=${CUTOFF}" | tee -a "$LOG"

for f in "$TEAM_FILE" "$PLAYER_FILE" "$SCHEDULE_CSV"; do
  if [[ ! -f "$f" ]]; then
    echo "ERROR: missing required file: $f" | tee -a "$LOG"
    exit 1
  fi
done

echo "--- Step 1/3: Build cache from feeds ---" | tee -a "$LOG"
python3 build_cbb_cache.py --team_file "$TEAM_FILE" --player_file "$PLAYER_FILE" --cutoff "$CUTOFF" --out_dir "$CACHE_DIR" | tee -a "$LOG"

echo "--- Step 2/3: Pull KenPom exports ---" | tee -a "$LOG"
python3 kenpom_pull.py --season "$SEASON" --out_dir "$CACHE_DIR" | tee -a "$LOG"

echo "--- Step 3/3: Build blended ratings + game inputs ---" | tee -a "$LOG"
python3 build_game_inputs_exemplary.py --cache_dir "$CACHE_DIR" --season "$SEASON" --schedule "$SCHEDULE_CSV" --out_dir "$CACHE_DIR" | tee -a "$LOG"

for f in "${CACHE_DIR}/BlendedRatings.csv" "${CACHE_DIR}/GameInputs.csv"; do
  if [[ ! -s "$f" ]]; then
    echo "ERROR: expected output missing or empty: $f" | tee -a "$LOG"
    exit 1
  fi
done

echo "=== Daily refresh completed successfully: ${TS} ===" | tee -a "$LOG"
