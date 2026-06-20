#!/usr/bin/env bash
set -euo pipefail

ROOT="/Volumes/移动硬盘（512G）/ReSETP"
SYSTEM_PYTHON="/opt/anaconda3/bin/python3.13"

if [ "$#" -lt 1 ]; then
  echo "usage: run_winner_formal_export.sh ATTEMPT_DIR" >&2
  exit 1
fi

ATTEMPT_DIR="$1"

cd "$ROOT"
export PYTHONHASHSEED=0
export SETP_ALNS_CRUSH_TRUE_REPAIR=0
export SETP_ALNS_CRUSH_ROUTE_ELIMINATION=0
export SETP_ALNS_CRUSH_TRUE_ACCEPTANCE=0
export SETP_ALNS_CRUSH_LOCAL_SEARCH=0
export SETP_ALNS_CRUSH_ADAPTIVE_Q=0
export PYTHONPATH="$ROOT/solver/src:$ROOT/solver/rl:$ROOT/models/src"

COMBINED="$ATTEMPT_DIR/combined"
if [ ! -f "$COMBINED/formal_runner_manifest.json" ]; then
  echo "Run merge_r2_manifests.py first" >&2
  exit 1
fi

echo "--- Exporting E0/T1 ---"
"$SYSTEM_PYTHON" -m setp_solver.search.formal_runner E0 \
  --repo-root "$ROOT" \
  --output-dir "$COMBINED" \
  --eval-budget 16000 --max-runtime-seconds 1800

echo "--- Re-exporting E1/T4/F1 seed-detail inputs ---"
"$SYSTEM_PYTHON" -m setp_solver.search.formal_runner E1 \
  --repo-root "$ROOT" \
  --output-dir "$COMBINED" \
  --eval-budget 16000 --max-runtime-seconds 1800 \
  --seeds 1,2,3,4,5,6,7,8,9,10

echo "--- Re-exporting E2/T3/F2/F1 route sources ---"
"$SYSTEM_PYTHON" -m setp_solver.search.formal_runner E2 \
  --repo-root "$ROOT" \
  --output-dir "$COMBINED" \
  --eval-budget 16000 --max-runtime-seconds 1800 \
  --seeds 1,2,3,4,5,6,7,8,9,10 \
  --exclude-algorithms DR-ALNS

echo "--- Re-exporting E3/T5 ---"
"$SYSTEM_PYTHON" -m setp_solver.search.formal_runner E3 \
  --repo-root "$ROOT" \
  --output-dir "$COMBINED" \
  --eval-budget 16000 --max-runtime-seconds 1800 \
  --seeds 1,2,3,4,5,6,7,8,9,10

echo "--- Re-exporting E4/T7/F5 ---"
"$SYSTEM_PYTHON" -m setp_solver.search.formal_runner E4 \
  --repo-root "$ROOT" \
  --output-dir "$COMBINED" \
  --eval-budget 16000 --max-runtime-seconds 1800 \
  --seeds 1,2,3,4,5,6,7,8,9,10 \
  --carbon-price-factors 0.5,1.0,2.0,4.0 \
  --quota-factors 0.5,0.8,1.0,1.2

echo "--- Re-exporting E6/T8/F6 ---"
"$SYSTEM_PYTHON" -m setp_solver.search.formal_runner E6 \
  --repo-root "$ROOT" \
  --output-dir "$COMBINED" \
  --eval-budget 16000 --max-runtime-seconds 1800 \
  --seeds 1,2,3,4,5,6,7,8,9,10 \
  --thetas 0.80,0.85,0.90,0.95,1.00,1.05,1.10

echo "--- Re-exporting E7/T9 ---"
"$SYSTEM_PYTHON" -m setp_solver.search.formal_runner E7 \
  --repo-root "$ROOT" \
  --output-dir "$COMBINED" \
  --eval-budget 16000 --max-runtime-seconds 1800 \
  --seeds 1,2,3,4,5,6,7,8,9,10

echo "--- Running E5 replay/T6/F3/F4 ---"
"$SYSTEM_PYTHON" -m setp_solver.search.formal_runner E5 \
  --repo-root "$ROOT" \
  --output-dir "$COMBINED" \
  --eval-budget 16000 --max-runtime-seconds 1800

echo "--- Running formal-backfill from combined only ---"
"$SYSTEM_PYTHON" -m setp_solver.reporting.runner formal-backfill \
  --repo-root "$ROOT" \
  --formal-dir "$COMBINED" \
  --output-dir "$ROOT/solver/reports/formal_winner_20260619"

echo "WINNER_FORMAL_EXPORT_COMPLETE $(date '+%Y-%m-%d %H:%M:%S')"
