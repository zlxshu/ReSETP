#!/usr/bin/env bash
set -euo pipefail

ROOT="/Volumes/移动硬盘（512G）/ReSETP"
ATTEMPT="${1:?usage: run_r2_recovery_chain.sh ATTEMPT_DIR [WORKERS]}"
WORKERS="${2:-6}"
LOG="$ATTEMPT/OPERATIONS_LOG.md"

cd "$ROOT"
export PYTHONPATH="solver/src"
mkdir -p "$ATTEMPT"/{logs,tables,figures}

log() {
  printf '| %s | %s |\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$*" | tee -a "$LOG"
}

run_cmd() {
  local label="$1"
  shift
  local cmd=("$@")
  log "START $label"
  {
    printf '\n## %s\n\n' "$label"
    printf 'command: `%q' "${cmd[0]}"
    for arg in "${cmd[@]:1}"; do
      printf ' %q' "$arg"
    done
    printf '`\n\n```text\n'
  } >> "$LOG"
  "${cmd[@]}" 2>&1 | tee -a "$LOG"
  local status="${PIPESTATUS[0]}"
  printf '```\n\n' >> "$LOG"
  if [[ "$status" -ne 0 ]]; then
    log "HALT $label exit=$status"
    exit "$status"
  fi
  log "DONE $label"
}

run_stage() {
  local stage="$1"
  local runtime="$2"
  shift 2
  run_cmd "S2 ${stage}" python -m setp_solver.search.formal_runner "$stage" \
    --repo-root "$ROOT" \
    --output-dir "$ATTEMPT" \
    --eval-budget 16000 \
    --max-runtime-seconds "$runtime" \
    "$@"
}

log "R2 recovery chain start attempt=$ATTEMPT requested_workers=$WORKERS"
log "Runtime note: formal_runner stages are currently sequential inside each stage; WORKERS is recorded for audit, not claimed as active parallelism."
log "Estimated upper bound: E2 160*1800s + E3 50*900s + E4 80*900s + E7 3*900s before algorithm early stops; observed prior E2/E7 timings are much lower."

run_stage E2 1800 --seeds 1,2,3,4,5,6,7,8,9,10
run_cmd "S2 E2 self-check actual evals" python - "$ATTEMPT" <<'PY'
import json, statistics, sys
from collections import defaultdict
from pathlib import Path
attempt = Path(sys.argv[1])
data = json.loads((attempt / "formal_runner_manifest.json").read_text(encoding="utf-8"))
groups = defaultdict(list)
for row in data.get("runs", []):
    key = row.get("key", {})
    if key.get("experiment") != "E2":
        continue
    result = row.get("result", {})
    value = result.get("actual_evals", result.get("evals"))
    if value not in (None, ""):
        groups[key.get("algorithm", "")].append(int(value))
for alg, vals in sorted(groups.items()):
    print(f"{alg}: n={len(vals)} min={min(vals)} median={statistics.median(vals)} max={max(vals)}")
PY

run_stage E3 900 --seeds 1,2,3,4,5,6,7,8,9,10 --variants M1,M2,M3,M4,M5
run_cmd "S2 E3 self-check" python - "$ATTEMPT" <<'PY'
import csv, json, sys
from collections import defaultdict
from pathlib import Path
attempt = Path(sys.argv[1])
data = json.loads((attempt / "formal_runner_manifest.json").read_text(encoding="utf-8"))
costs = defaultdict(dict)
for row in data.get("runs", []):
    key = row.get("key", {})
    if key.get("experiment") != "E3" or row.get("status") != "completed":
        continue
    result = row.get("result", {})
    if result.get("feasible") and result.get("best_cost") not in (None, ""):
        costs[key["variant"]][int(key["seed"])] = float(result["best_cost"])
for variant in sorted(costs):
    vals = list(costs[variant].values())
    print(f"{variant}: n={len(vals)} mean={sum(vals)/len(vals):.6f}")
if "M0" in costs and "M1" in costs:
    mean0 = sum(costs["M0"].values()) / len(costs["M0"])
    mean1 = sum(costs["M1"].values()) / len(costs["M1"])
    if mean1 > mean0 + 1e-6:
        print("HALT_E3_M1_GT_M0", mean1, mean0)
        sys.exit(2)
print("E3_SELF_CHECK_PASS")
PY

run_stage E4 900 --seeds 1,2,3,4,5
run_cmd "S2 E4 self-check" python - "$ATTEMPT" <<'PY'
import csv, sys
from pathlib import Path
attempt = Path(sys.argv[1])
rows = list(csv.DictReader((attempt / "tables" / "t7_carbon_sensitivity.csv").open(encoding="utf-8")))
values = {row["total_carbon_kg"] for row in rows if row.get("total_carbon_kg")}
print(f"E4 carbon unique values={len(values)} values={sorted(values)[:20]}")
if len(values) <= 1:
    print("HALT_E4_CARBON_CONSTANT")
    sys.exit(2)
print("E4_SELF_CHECK_PASS")
PY

run_stage E7 900 --seeds 1,2,3
run_cmd "S2 E7 self-check" python - "$ATTEMPT" <<'PY'
import json, sys
from pathlib import Path
attempt = Path(sys.argv[1])
data = json.loads((attempt / "formal_runner_manifest.json").read_text(encoding="utf-8"))
bad = []
for row in data.get("runs", []):
    key = row.get("key", {})
    if key.get("experiment") != "E7":
        continue
    result = row.get("result", {})
    dyn = result.get("dynamic_final_control", {})
    sta = result.get("static_revealed_control", {})
    info = result.get("information_cost", 0.0)
    print(f"seed={key.get('seed')} dynamic={dyn.get('feasible')} static={sta.get('feasible')} info_cost={info}")
    if not dyn.get("feasible") or not sta.get("feasible") or float(info) < -1e-6 or not result.get("all_assertions_pass"):
        bad.append({"key": key, "gate": result.get("gate"), "dynamic": dyn, "static": sta, "info": info})
if bad:
    print("HALT_E7_SELF_CHECK", json.dumps(bad, ensure_ascii=False)[:4000])
    sys.exit(2)
print("E7_SELF_CHECK_PASS")
PY

run_cmd "S3 formal-backfill" python -m setp_solver.reporting.runner formal-backfill \
  --repo-root "$ROOT" \
  --formal-dir "$ATTEMPT" \
  --output-dir "$ROOT/solver/reports"

log "HALT_FOR_USER R2 recovery chain completed S2/S3 gates"
