# run_daily_marketmaker_release.sh

Operator workflow:

1. Open the control workbook in Excel.
2. Update:
   - Odds_from_Odds_Api_Spread
   - Odds_from_Odds_Api_Total
3. Save and close Excel.
4. Export:
   - KPC_API_KEY
   - KPC_BASE_URL
5. Run:
   bash ./run_daily_marketmaker_release.sh YYYY-MM-DD
6. Open the finished workbook.

Defaults:
- control workbook:
  ../ncaab_marketmaker_PMF_pricing_model_2026-03-15_STABLE.xlsm
- side:
  point2

Example:
  export KPC_API_KEY="YOUR_KENPOM_KEY"
  export KPC_BASE_URL="https://kenpom.com"
  bash ./run_daily_marketmaker_release.sh 2026-03-18

Optional:
  bash ./run_daily_marketmaker_release.sh 2026-03-18 point2 "/full/path/to/control_workbook.xlsm"
