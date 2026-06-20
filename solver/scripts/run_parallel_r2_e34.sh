#!/usr/bin/env bash
set -euo pipefail

ROOT="/Volumes/移动硬盘（512G）/ReSETP"

if [ "$#" -lt 2 ]; then
  echo "usage: run_parallel_r2.sh ATTEMPT_DIR MODE" >&2
  exit 1
fi

ATTEMPT_DIR="$1"
MODE="$2"

if [ "$MODE" = "dryrun" ]; then
  BUDGET=200000
  E2_RUNTIME=15
  E3_RUNTIME=15
  E4_RUNTIME=15
  E7_RUNTIME=15
elif [ "$MODE" = "full" ]; then
  BUDGET=16000
  E2_RUNTIME=1800
  E3_RUNTIME=900
  E4_RUNTIME=900
  E7_RUNTIME=900
else
  echo "MODE must be dryrun or full" >&2
  exit 1
fi

cd "$ROOT"
export PYTHONPATH="$ROOT/solver/src"
export R="$ROOT"
export A="$ATTEMPT_DIR"
export B="$BUDGET"
export T2="$E2_RUNTIME"
export T3="$E3_RUNTIME"
export T4="$E4_RUNTIME"
export T7="$E7_RUNTIME"

mkdir -p "$ATTEMPT_DIR/units" "$ATTEMPT_DIR/logs"

UNIT_IDS=()
UNIT_STAGES=()
UNIT_SEEDS=()
UNIT_RUNTIMES=()
UNIT_EXTRA_ARGS=()

add_unit() {
  local unit_id="$1"
  local stage="$2"
  local seeds="$3"
  local runtime="$4"
  local extra_args="${5:-}"
  UNIT_IDS+=("$unit_id")
  UNIT_STAGES+=("$stage")
  UNIT_SEEDS+=("$seeds")
  UNIT_RUNTIMES+=("$runtime")
  UNIT_EXTRA_ARGS+=("$extra_args")
}

for seed in 1 2 3 4 5 6 7 8 9 10; do
  add_unit "e3_s${seed}" "E3" "$seed" "$E3_RUNTIME" "--variants M1,M2,M3,M4,M5"
done

for seed in 1 2 3 4 5; do
  add_unit "e4_s${seed}" "E4" "$seed" "$E4_RUNTIME"
done

for unit_id in "${UNIT_IDS[@]}"; do
  mkdir -p "$ATTEMPT_DIR/units/$unit_id"
done

: > "$ATTEMPT_DIR/unit_commands.txt"
for idx in "${!UNIT_IDS[@]}"; do
  unit_id="${UNIT_IDS[$idx]}"
  stage="${UNIT_STAGES[$idx]}"
  seeds="${UNIT_SEEDS[$idx]}"
  runtime="${UNIT_RUNTIMES[$idx]}"
  extra_args="${UNIT_EXTRA_ARGS[$idx]}"
  if [ -n "$extra_args" ]; then
    printf 'PYTHONPATH="$R/solver/src" python -m setp_solver.search.formal_runner %s --repo-root "$R" --output-dir "$A/units/%s" --eval-budget "$B" --max-runtime-seconds "%s" --seeds %s %s > "$A/logs/%s.log" 2>&1\n' \
      "$stage" "$unit_id" "$runtime" "$seeds" "$extra_args" "$unit_id" >> "$ATTEMPT_DIR/unit_commands.txt"
  else
    printf 'PYTHONPATH="$R/solver/src" python -m setp_solver.search.formal_runner %s --repo-root "$R" --output-dir "$A/units/%s" --eval-budget "$B" --max-runtime-seconds "%s" --seeds %s > "$A/logs/%s.log" 2>&1\n' \
      "$stage" "$unit_id" "$runtime" "$seeds" "$unit_id" >> "$ATTEMPT_DIR/unit_commands.txt"
  fi
done

line_count="$(grep -cve '^[[:space:]]*$' "$ATTEMPT_DIR/unit_commands.txt")"
if [ "$line_count" -ne 15 ]; then
  echo "unit_commands.txt has $line_count non-empty lines, expected 15" >&2
  exit 1
fi

START_SECONDS=$SECONDS
set +e
xargs -P 6 -I CMD bash -c 'CMD' < "$ATTEMPT_DIR/unit_commands.txt"
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
    head -20 "$f"
  done <<< "$ERROR_FILES"
fi

echo "XARGS_EXIT=$XARGS_EXIT"
echo "PARALLEL_R2 MODE=$MODE PASS=$PASS_COUNT FAIL=$FAIL_COUNT ELAPSED=${ELAPSED}s"

if [ "$FAIL_COUNT" -eq 0 ]; then
  exit 0
fi
exit 2
