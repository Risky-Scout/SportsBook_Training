#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo 'Usage: ./run_daily_marketmaker_exemplary.sh "path/to/workbook.xlsm" YYYY-MM-DD [point1|point2]'
  exit 1
fi

WORKBOOK="$1"
SLATE_DATE="$2"
SPREAD_SIDE="${3:-point1}"

bash ./run_daily_from_workbook_two_tabs.sh "$WORKBOOK" "$SLATE_DATE" "$SPREAD_SIDE"

OUT="./ncaab_pmf_model_DAILY_${SLATE_DATE}_MARKET_MAKER_PRO.xlsx"

python3 ./postbuild_fix_spreadtotal_curves.py --workbook "$OUT"

python3 ./qa_marketmaker_daily.py \
  --workbook "$OUT" \
  --gameinputs "./cbb_cache/GameInputs.csv" \
  --blended "./cbb_cache/BlendedRatings.csv"

echo "READY: $OUT"
