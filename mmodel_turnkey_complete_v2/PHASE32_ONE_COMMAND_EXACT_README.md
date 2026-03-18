# Phase 3.2 One-Command Exact Generator

## Purpose
Runs the full exact-workbook pipeline in one command:

1. build exact PMF outputs
2. validate exact PMF outputs
3. build the exact workbook
4. repair workbook math / dashboard / sign semantics
5. run exact-mode QA

## Usage
```bash
chmod +x run_daily_marketmaker_v3_exact.sh
bash ./run_daily_marketmaker_v3_exact.sh YYYY-MM-DD
```

Example:
```bash
bash ./run_daily_marketmaker_v3_exact.sh 2026-03-17
```

## Output
The final workbook path is:

```text
./outputs_exact_workbook/ncaab_pmf_model_DAILY_YYYY-MM-DD_MARKET_MAKER_PRO_V2_EXACT.xlsx
```

## Notes
This Phase 3.2 generator uses the exact-workbook QA:

```bash
python3 ./qa_marketmaker_exact_v3.py --workbook <output workbook>
```

It is intended for the exact workbook path, not the baseline normal-curve workbook.
