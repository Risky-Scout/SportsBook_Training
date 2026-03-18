#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo 'Usage: ./run_daily_marketmaker_v2_exact.sh YYYY-MM-DD'
  exit 1
fi

SLATE_DATE="$1"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

BASE_WORKBOOK="../ncaab_pmf_model_DAILY_${SLATE_DATE}_MARKET_MAKER_PRO.xlsx"
SUMMARY_CSV="./outputs/exact_pmf_game_summary_${SLATE_DATE}.csv"
MARGIN_CSV="./outputs/exact_margin_pmf_${SLATE_DATE}.csv"
TOTAL_CSV="./outputs/exact_total_pmf_${SLATE_DATE}.csv"
OUT_DIR="./outputs_exact_workbook"
OUT_WORKBOOK="${OUT_DIR}/ncaab_pmf_model_DAILY_${SLATE_DATE}_MARKET_MAKER_PRO_V2_EXACT.xlsx"

mkdir -p "$OUT_DIR"

python3 ./inject_joint_pmf_into_workbook_v2.py \
  --base_workbook "$BASE_WORKBOOK" \
  --summary_csv "$SUMMARY_CSV" \
  --margin_csv "$MARGIN_CSV" \
  --total_csv "$TOTAL_CSV" \
  --out_workbook "$OUT_WORKBOOK"

echo "READY: $OUT_WORKBOOK"
