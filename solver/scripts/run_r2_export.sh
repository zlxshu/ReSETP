#!/usr/bin/env bash
set -euo pipefail

ROOT="/Volumes/移动硬盘（512G）/ReSETP"

if [ "$#" -lt 1 ]; then
  echo "usage: run_r2_export.sh ATTEMPT_DIR" >&2
  exit 1
fi

ATTEMPT_DIR="$1"

cd "$ROOT"
export PYTHONPATH="$ROOT/solver/src"

if [ ! -f "$ATTEMPT_DIR/combined/formal_runner_manifest.json" ]; then
  echo "Run merge_r2_manifests.py first" >&2
  exit 1
fi

echo "--- Re-exporting E2 CSVs (runs will be skipped by ledger) ---"
python -m setp_solver.search.formal_runner E2 \
  --repo-root "$ROOT" \
  --output-dir "$ATTEMPT_DIR/combined" \
  --eval-budget 16000 --max-runtime-seconds 1800 \
  --seeds 1,2,3,4,5,6,7,8,9,10
echo "E2_EXPORT exit=$?"

echo "--- Re-exporting E3 CSVs ---"
python -m setp_solver.search.formal_runner E3 \
  --repo-root "$ROOT" \
  --output-dir "$ATTEMPT_DIR/combined" \
  --eval-budget 16000 --max-runtime-seconds 900 \
  --seeds 1,2,3,4,5,6,7,8,9,10 \
  --variants M1,M2,M3,M4,M5
echo "E3_EXPORT exit=$?"

echo "--- Re-exporting E4 CSVs ---"
python -m setp_solver.search.formal_runner E4 \
  --repo-root "$ROOT" \
  --output-dir "$ATTEMPT_DIR/combined" \
  --eval-budget 16000 --max-runtime-seconds 900 \
  --seeds 1,2,3,4,5
echo "E4_EXPORT exit=$?"

echo "--- Re-exporting E7 CSVs ---"
python -m setp_solver.search.formal_runner E7 \
  --repo-root "$ROOT" \
  --output-dir "$ATTEMPT_DIR/combined" \
  --eval-budget 16000 --max-runtime-seconds 900 \
  --seeds 1,2,3
echo "E7_EXPORT exit=$?"

echo "--- Running formal-backfill ---"
python -m setp_solver.reporting.runner formal-backfill \
  --repo-root "$ROOT" \
  --formal-dir "$ATTEMPT_DIR/combined" \
  --output-dir "$ROOT/solver/reports"
echo "BACKFILL exit=$?"

echo "R2_EXPORT_COMPLETE $(date '+%Y-%m-%d %H:%M:%S')"
