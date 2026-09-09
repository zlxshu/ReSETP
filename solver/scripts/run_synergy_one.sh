#!/bin/zsh
# 2026-09-05 运行协议：M1 4 性能核，交付批 ≤3 并行、不降优先级。
# 独立配送的单个任务：run_synergy_one.sh <OUT_ROOT> <run>
# 幂等：已有 best_solution.json 的跳过；求解器自己创建输出目录。
# DRY_RUN=1 时只睡 2 秒，用于验证调用接线。
set -u
OUT_ROOT="$1"; run="$2"
REPO="$(cd "$(dirname "$0")/../.." && pwd -P)"
cd "$REPO"
PY="$REPO/.public-hgs-venv/bin/python3"
export PYTHONPATH='solver/src:third_party/setp_hgs_kernel:models/src'
dir="$OUT_ROOT/independent/run_$run"
if [[ -f "$dir/best_solution.json" ]]; then print "跳过 independent/run_$run（已完成）"; exit 0; fi
mkdir -p "$OUT_ROOT/independent"
COMMON=(
  --instance-id cn-jjj-50c-01-DEPOTSEARCH-d996f755bd
  --carbon-price 0.2
  --fleet-parameter-class endogenous
  --population-mode copied_hgs_defaults
  --recharge-mode on_demand
  --depot-curve registered
  --charge-timing-policy cost_plus_carbon
  --charging-prescreen
  --search-mode kernel_native
  --no-ev-charge-time-proxy
  --ev-reload-gap-proxy
  --confirming-round
)
flags=(--mechanism-off cross_depot)
if [[ "${DRY_RUN:-0}" == "1" ]]; then print "[$(date +%H:%M:%S)] DRY independent/run_$run"; sleep 2; exit 0; fi
print "[$(date +%H:%M:%S)] 启动 independent/run_$run"
"$PY" solver/scripts/run_problem_hgs_private_technical.py \
    "$dir" --data-repo-root . --arm independent "${COMMON[@]}" "${flags[@]}" \
    >> "$OUT_ROOT/independent/run_$run.log" 2>&1
rc=$?
print "[$(date +%H:%M:%S)] 完成 independent/run_$run exit=$rc"
exit "$rc"
