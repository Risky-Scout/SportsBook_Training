#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo 'Usage: ./run_joint_pmf_exact_v2.sh YYYY-MM-DD'
  exit 1
fi

SLATE_DATE="$1"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

mkdir -p "./outputs/grids"

python3 ./build_joint_pmf_exact_v2.py \
  --gameinputs "../cbb_cache/GameInputs.csv" \
  --blended "../cbb_cache/BlendedRatings.csv" \
  --params "./exact_pmf_params_v2.json" \
  --out_dir "./outputs" \
  --cutoff "$SLATE_DATE"
