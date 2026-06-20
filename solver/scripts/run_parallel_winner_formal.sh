#!/usr/bin/env bash
set -euo pipefail

ROOT="/Volumes/移动硬盘（512G）/ReSETP"
SYSTEM_PYTHON="/opt/anaconda3/bin/python3.13"

if [ "$#" -lt 2 ]; then
  echo "usage: run_parallel_winner_formal.sh ATTEMPT_DIR MODE [PARALLEL]" >&2
  exit 1
fi

ATTEMPT_DIR="$1"
MODE="$2"
PARALLEL="${3:-6}"

if [ "$MODE" = "dryrun" ]; then
  BUDGET=200000
  RUNTIME=15
elif [ "$MODE" = "full" ]; then
  BUDGET=16000
  RUNTIME=1800
else
  echo "MODE must be dryrun or full" >&2
  exit 1
fi

cd "$ROOT"
export PYTHONHASHSEED=0
export SETP_ALNS_CRUSH_TRUE_REPAIR=0
export SETP_ALNS_CRUSH_ROUTE_ELIMINATION=0
export SETP_ALNS_CRUSH_TRUE_ACCEPTANCE=0
export SETP_ALNS_CRUSH_LOCAL_SEARCH=0
export SETP_ALNS_CRUSH_ADAPTIVE_Q=0
export PYTHONPATH="$ROOT/solver/src:$ROOT/solver/rl:$ROOT/models/src"
export R="$ROOT"
export A="$ATTEMPT_DIR"
export B="$BUDGET"
export T="$RUNTIME"
export PY="$SYSTEM_PYTHON"

mkdir -p "$ATTEMPT_DIR/units" "$ATTEMPT_DIR/logs"

UNIT_IDS=()
UNIT_STAGES=()
UNIT_SEEDS=()
UNIT_EXTRA_ARGS=()

add_unit() {
  local unit_id="$1"
  local stage="$2"
  local seeds="$3"
  local extra_args="${4:-}"
  UNIT_IDS+=("$unit_id")
  UNIT_STAGES+=("$stage")
  UNIT_SEEDS+=("$seeds")
  UNIT_EXTRA_ARGS+=("$extra_args")
}

for seed in 1 2 3 4 5 6 7 8 9 10; do
  add_unit "e1_s${seed}" "E1" "$seed"
  add_unit "e2_s${seed}" "E2" "$seed" "--exclude-algorithms DR-ALNS"
  add_unit "e3_s${seed}" "E3" "$seed"
  add_unit "e4_s${seed}" "E4" "$seed" "--carbon-price-factors 0.5,1.0,2.0,4.0 --quota-factors 0.5,0.8,1.0,1.2"
  add_unit "e6_s${seed}" "E6" "$seed" "--thetas 0.80,0.85,0.90,0.95,1.00,1.05,1.10"
  add_unit "e7_s${seed}" "E7" "$seed"
done

for unit_id in "${UNIT_IDS[@]}"; do
  mkdir -p "$ATTEMPT_DIR/units/$unit_id"
done

QUOTA_SOURCE="${QUOTA_SOURCE:-$ROOT/solver/reports/formal_winner_20260619/formal/carbon_quota_L-main.json}"
if [ -f "$QUOTA_SOURCE" ]; then
  cp "$QUOTA_SOURCE" "$ATTEMPT_DIR/carbon_quota_L-main.json"
  for unit_id in "${UNIT_IDS[@]}"; do
    cp "$QUOTA_SOURCE" "$ATTEMPT_DIR/units/$unit_id/carbon_quota_L-main.json"
  done
fi

: > "$ATTEMPT_DIR/unit_commands.txt"
for idx in "${!UNIT_IDS[@]}"; do
  unit_id="${UNIT_IDS[$idx]}"
  stage="${UNIT_STAGES[$idx]}"
  seeds="${UNIT_SEEDS[$idx]}"
  extra_args="${UNIT_EXTRA_ARGS[$idx]}"
  if [ -n "$extra_args" ]; then
    printf '"$PY" -m setp_solver.search.formal_runner %s --repo-root "$R" --output-dir "$A/units/%s" --eval-budget "$B" --max-runtime-seconds "$T" --seeds %s %s > "$A/logs/%s.log" 2>&1\n' \
      "$stage" "$unit_id" "$seeds" "$extra_args" "$unit_id" >> "$ATTEMPT_DIR/unit_commands.txt"
  else
    printf '"$PY" -m setp_solver.search.formal_runner %s --repo-root "$R" --output-dir "$A/units/%s" --eval-budget "$B" --max-runtime-seconds "$T" --seeds %s > "$A/logs/%s.log" 2>&1\n' \
      "$stage" "$unit_id" "$seeds" "$unit_id" >> "$ATTEMPT_DIR/unit_commands.txt"
  fi
done

line_count="$(grep -cve '^[[:space:]]*$' "$ATTEMPT_DIR/unit_commands.txt")"
if [ "$line_count" -ne 60 ]; then
  echo "unit_commands.txt has $line_count non-empty lines, expected 60" >&2
  exit 1
fi

START_SECONDS=$SECONDS
set +e
xargs -P "$PARALLEL" -I CMD bash -c 'CMD' < "$ATTEMPT_DIR/unit_commands.txt"
XARGS_EXIT=$?
set -e
ELAPSED=$(( SECONDS - START_SECONDS ))

PASS_COUNT=0
FAIL_COUNT=0
for unit_id in "${UNIT_IDS[@]}"; do
  if [ -f "$ATTEMPT_DIR/units/$unit_id/formal_runner_manifest.json" ]; then
    PASS_COUNT=$((PASS_COUNT + 1))
  else
    FAIL_COUNT=$((FAIL_COUNT + 1))
    echo "MISSING_MANIFEST: $unit_id" >&2
  fi
done

ERROR_FILES="$(grep -l "Traceback\\|Error:" "$ATTEMPT_DIR/logs/"*.log 2>/dev/null || true)"
if [ -n "$ERROR_FILES" ]; then
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    echo "ERROR_LOG: $f"
    head -40 "$f"
  done <<< "$ERROR_FILES"
fi

echo "XARGS_EXIT=$XARGS_EXIT"
echo "PARALLEL_WINNER_FORMAL MODE=$MODE PASS=$PASS_COUNT FAIL=$FAIL_COUNT ELAPSED=${ELAPSED}s"

if [ "$XARGS_EXIT" -eq 0 ] && [ "$FAIL_COUNT" -eq 0 ]; then
  exit 0
fi
exit 2
