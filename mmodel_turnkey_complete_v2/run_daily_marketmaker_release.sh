#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  ./run_daily_marketmaker_release.sh YYYY-MM-DD [point1|point2] [optional_control_workbook_path]

Examples:
  ./run_daily_marketmaker_release.sh 2026-03-18
  ./run_daily_marketmaker_release.sh 2026-03-18 point2
  ./run_daily_marketmaker_release.sh 2026-03-18 point2 "/full/path/to/control_workbook.xlsm"

What this does:
  1) Rebuilds Schedule.csv / GameInputs.csv / BlendedRatings.csv from the control workbook
  2) Builds exact PMF outputs
  3) Builds exact workbook
  4) Applies stable workbook cleanup patches
  5) Runs exact QA
  6) Removes broken embedded SpreadTotal charts for now
  7) Prints final output path

Before running:
  - Update the odds tabs in the control workbook
  - Save and close Excel
  - Export KPC_API_KEY and KPC_BASE_URL
USAGE
}

if [[ $# -lt 1 ]]; then
  usage
  exit 1
fi

DATE="$1"
SIDE="${2:-point2}"

if [[ "$DATE" == "YYYY-MM-DD" || "$DATE" == *"YYYY"* || "$DATE" == *"MM"* || "$DATE" == *"DD"* ]]; then
  echo "ERROR: replace YYYY-MM-DD with a real date, e.g. 2026-03-18"
  exit 1
fi

if [[ ! "$DATE" =~ ^20[0-9]{2}-[0-9]{2}-[0-9]{2}$ ]]; then
  echo "ERROR: date must be in YYYY-MM-DD format, e.g. 2026-03-18"
  exit 1
fi

if [[ "$SIDE" != "point1" && "$SIDE" != "point2" ]]; then
  echo "ERROR: side must be point1 or point2"
  exit 1
fi

if [[ -z "${KPC_API_KEY:-}" ]]; then
  echo "ERROR: KPC_API_KEY is not set"
  exit 1
fi

if [[ -z "${KPC_BASE_URL:-}" ]]; then
  echo "ERROR: KPC_BASE_URL is not set"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

DEFAULT_CONTROL="$BASE_DIR/ncaab_marketmaker_PMF_pricing_model_2026-03-15_STABLE.xlsm"
CONTROL="${3:-$DEFAULT_CONTROL}"

LAB_DIR="$SCRIPT_DIR"
OUT="$LAB_DIR/outputs_exact_workbook/ncaab_pmf_model_DAILY_${DATE}_MARKET_MAKER_PRO_V2_EXACT.xlsx"

if [[ ! -f "$CONTROL" ]]; then
  echo "ERROR: control workbook not found: $CONTROL"
  exit 1
fi

required_scripts=(
  "$BASE_DIR/run_daily_from_workbook_two_tabs.sh"
  "$LAB_DIR/run_joint_pmf_exact_v2.sh"
  "$LAB_DIR/validate_joint_pmf_v2.py"
  "$LAB_DIR/run_daily_marketmaker_v2_exact.sh"
  "$LAB_DIR/repair_exact_workbook_math_v2.py"
  "$LAB_DIR/patch_dashboard_selected_block_v2.py"
  "$LAB_DIR/patch_sign_semantics_v2.py"
  "$LAB_DIR/patch_dashboard_snapshot_semantics_v2.py"
  "$LAB_DIR/patch_dashboard_line_view_v2.py"
  "$LAB_DIR/patch_consistent_home_line_signs_v3.py"
  "$LAB_DIR/patch_spreadtotal_exact_cleanup_v2.py"
  "$LAB_DIR/qa_marketmaker_exact_v3.py"
)

for f in "${required_scripts[@]}"; do
  if [[ ! -f "$f" ]]; then
    echo "ERROR: required file missing: $f"
    exit 1
  fi
done

echo "=== DAILY MARKETMAKER RELEASE START ==="
echo "DATE=$DATE"
echo "SIDE=$SIDE"
echo "CONTROL=$CONTROL"

echo "--- 1/7 Rebuild upstream inputs from control workbook ---"
cd "$BASE_DIR"
bash ./run_daily_from_workbook_two_tabs.sh "$CONTROL" "$DATE" "$SIDE"

echo "--- Canonicalize extracted team names ---"
python3 ./canonicalize_odds_names_v1.py
python3 ./snap_market_lines_to_half_points_v2.py

echo "--- Sanity check: Schedule/GameInputs ---"
head -10 "$BASE_DIR/Schedule.csv" || true
head -10 "$BASE_DIR/cbb_cache/GameInputs.csv" || true

echo "--- 2/7 Build exact PMF outputs ---"
cd "$LAB_DIR"
bash ./run_joint_pmf_exact_v2.sh "$DATE"

echo "--- 3/7 Validate exact PMF outputs ---"
python3 ./validate_joint_pmf_v2.py --out_dir ./outputs --cutoff "$DATE"

echo "--- 4/7 Build exact workbook ---"
bash ./run_daily_marketmaker_v2_exact.sh "$DATE"

echo "--- 5/7 Apply stable workbook patches ---"
python3 ./repair_exact_workbook_math_v2.py --workbook "$OUT"
python3 ./patch_workbook_market_lines_to_half_points_v1.py --workbook "$OUT"
python3 ./patch_dashboard_selected_block_v2.py --workbook "$OUT"
python3 ./patch_sign_semantics_v2.py --workbook "$OUT"
python3 ./patch_dashboard_snapshot_semantics_v2.py --workbook "$OUT"
python3 ./patch_dashboard_line_view_v2.py --workbook "$OUT"
python3 ./patch_consistent_home_line_signs_v3.py --workbook "$OUT"
python3 ./patch_spreadtotal_exact_cleanup_v2.py --workbook "$OUT"
python3 ./patch_marketmaker_board_headers_v3.py --workbook "$OUT"
python3 ./patch_trader_sign_semantics_v4.py --workbook "$OUT"

echo "--- 6/7 Exact QA ---"
python3 ./qa_marketmaker_exact_v3.py --workbook "$OUT"

echo "--- 7/7 Remove broken embedded SpreadTotal charts for now ---"
python3 - <<PY
from openpyxl import load_workbook
path = r"$OUT"
wb = load_workbook(path)
ws = wb["SpreadTotal"]
ws._charts = []
ws["J28"] = "Charts temporarily removed."
ws["J29"] = "Use the exact PMF tables above for pricing/interpretation."
ws["J30"] = "Embedded Excel charts are under rebuild."
ws["J31"] = "Workbook tables remain the source of truth."
wb.save(path)
print(f"Removed broken SpreadTotal charts and saved workbook: {path}")
PY

echo "=== RELEASE COMPLETE ==="
echo "OUTPUT=$OUT"
echo
echo "Next:"
echo "  open -a \"Microsoft Excel\" \"$OUT\""
