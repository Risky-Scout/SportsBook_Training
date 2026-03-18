#!/usr/bin/env bash
set -euo pipefail

: "${KPC_API_KEY:?Missing KPC_API_KEY env var}"
: "${KPC_BASE_URL:=https://kenpom.com}"

if [[ $# -lt 2 ]]; then
  echo 'Usage: run_daily_from_workbook_two_tabs.sh "path/to/workbook.xlsm" YYYY-MM-DD [point1|point2]'
  exit 1
fi

WORKBOOK="$1"
SLATE_DATE="$2"
SPREAD_SIDE="${3:-point1}"

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

CACHE_DIR="./cbb_cache"
FEEDS_DIR="./feeds_daily"
SEASON="2026"

TEAM_FILE="$(ls -1 ${FEEDS_DIR}/*team-feed*.xlsx 2>/dev/null | sort | tail -n 1 || true)"
PLAYER_FILE="$(ls -1 ${FEEDS_DIR}/*player-feed*.xlsx 2>/dev/null | sort | tail -n 1 || true)"

if [[ -z "${TEAM_FILE}" || -z "${PLAYER_FILE}" ]]; then
  echo "Missing feed files in ${FEEDS_DIR}"
  exit 1
fi

mkdir -p "$CACHE_DIR" "./logs"
TS="$(date +"%Y%m%d_%H%M%S")"
LOG="./logs/daily_from_workbook_two_tabs_${TS}.log"

FEED_CUTOFF="$(python3 - <<PY
import pandas as pd
df = pd.read_excel(r"$TEAM_FILE", sheet_name="CBB-2025-26-TEAM", usecols=["DATE"])
df["DATE"] = pd.to_datetime(df["DATE"], errors="coerce")
print(df["DATE"].max().date().isoformat())
PY
)"

echo "WORKBOOK=${WORKBOOK}" | tee -a "$LOG"
echo "SLATE_DATE=${SLATE_DATE}" | tee -a "$LOG"
echo "SPREAD_SIDE=${SPREAD_SIDE}" | tee -a "$LOG"
echo "TEAM_FILE=${TEAM_FILE}" | tee -a "$LOG"
echo "PLAYER_FILE=${PLAYER_FILE}" | tee -a "$LOG"
echo "FEED_CUTOFF=${FEED_CUTOFF}" | tee -a "$LOG"

python3 extract_schedule_from_workbook_two_tabs.py \
  --workbook "$WORKBOOK" \
  --date "$SLATE_DATE" \
  --spread-side "$SPREAD_SIDE" \
  --out-schedule "./Schedule.csv" \
  --out-normalized "./odds_normalized_${SLATE_DATE}.csv" | tee -a "$LOG"

python3 build_cbb_cache.py \
  --team_file "$TEAM_FILE" \
  --player_file "$PLAYER_FILE" \
  --cutoff "$FEED_CUTOFF" \
  --out_dir "$CACHE_DIR" | tee -a "$LOG"

python3 kenpom_pull.py \
  --season "$SEASON" \
  --out_dir "$CACHE_DIR" | tee -a "$LOG"

python3 build_game_inputs_exemplary.py \
  --cache_dir "$CACHE_DIR" \
  --season "$SEASON" \
  --schedule "./Schedule.csv" \
  --out_dir "$CACHE_DIR" \
  | tee -a "$LOG"

python3 build_daily_workbook_marketmaker_pro.py \
  --out "./ncaab_pmf_model_DAILY_${SLATE_DATE}_MARKET_MAKER_PRO.xlsx" \
  --cache_dir "$CACHE_DIR" \
  --season "$SEASON" | tee -a "$LOG"

echo "DONE: ./ncaab_pmf_model_DAILY_${SLATE_DATE}_MARKET_MAKER_PRO.xlsx" | tee -a "$LOG"
