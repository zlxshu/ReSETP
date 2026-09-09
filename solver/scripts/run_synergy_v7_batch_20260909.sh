#!/bin/zsh
# 2026-09-09：4.5 独立配送 vs 联合配送对比批（v7），改用最近车场见证解起手。
# 每臂 10 次独立运行；除 --witness-path 与 --mechanism-off 外，逐条沿用
# run_synergy_one.sh 的参数块。没有随机种子开关：run_synergy_one.sh 只靠
# 输出目录区分次数，次与次之间的差异来自求解器自身未播种的随机性。
set -u
REPO="/Volumes/移动硬盘（512G）/ReSETP"
cd "$REPO"
PY="$REPO/.public-hgs-venv/bin/python3"
export PYTHONPATH='solver/src:third_party/setp_hgs_kernel:models/src'

OUT="solver/reports/synergy_v7_20260909"
BATCH_LOG="solver/reports/synergy_v7_20260909_batch.log"
WITNESS="solver/reports/instance_build_only_d996f755bd_20260815/health_witness_routes_nearest_depot.csv"
PARALLEL="${PARALLEL:-2}"

mkdir -p "$OUT/independent" "$OUT/joint"

log() { print "[$(date +%H:%M:%S)] $1" >> "$BATCH_LOG" }

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
  --witness-path "$WITNESS"
  --depot-lock-penalty 1e8
)

run_one() {  # $1=independent|joint  $2=运行序号（01..10）
  local arm="$1" run="$2"
  local dir="$OUT/$arm/run_$run"
  local tag="$arm/run_$run"
  if [[ -f "$dir/best_solution.json" ]]; then
    log "跳过 $tag（已完成）"
    return 0
  fi
  local flags=()
  if [[ "$arm" == "independent" ]]; then
    flags=(--mechanism-off cross_depot)
  fi
  log "启动 $tag"
  "$PY" solver/scripts/run_problem_hgs_private_technical.py \
      "$dir" --data-repo-root . --arm "$arm" "${COMMON[@]}" "${flags[@]}" \
      >> "$OUT/$arm/run_$run.log" 2>&1
  local rc=$?
  log "完成 $tag exit=$rc"
  return $rc
}

# 先等联盟批跑完，避免抢 4 个性能核。
waited=0
while pgrep -f run_coalition_experiment.py > /dev/null 2>&1; do
  if (( waited == 0 )); then
    log "检测到 run_coalition_experiment.py 仍在跑，开始等待（每60秒轮询一次）"
    waited=1
  fi
  sleep 60
done
if (( waited == 1 )); then
  log "run_coalition_experiment.py 已结束，开始本批"
else
  log "未检测到 run_coalition_experiment.py，直接开始本批"
fi

# 20 个任务排成一条队列：先 10 次独立配送，再 10 次联合配送。
jobs_arm=(); jobs_run=()
for arm in independent joint; do
  for run in 01 02 03 04 05 06 07 08 09 10; do
    jobs_arm+=("$arm"); jobs_run+=("$run")
  done
done

# 流水线式工作池：任何一个跑完就立刻补下一个，不等整波。
pids=()
next=1
total=${#jobs_arm}
while (( next <= total )) || (( ${#pids} > 0 )); do
  while (( ${#pids} < PARALLEL )) && (( next <= total )); do
    run_one "${jobs_arm[$next]}" "${jobs_run[$next]}" &
    pids+=($!)
    (( next++ ))
  done
  sleep 5
  alive=()
  for pid in "${pids[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      alive+=("$pid")
    else
      wait "$pid" 2>/dev/null
    fi
  done
  pids=("${alive[@]}")
done

log "本批结束，汇总 evaluation.total_cost"
{
  printf '%-22s %s\n' "运行" "总成本(元)"
  for i in {1..$total}; do
    arm="${jobs_arm[$i]}"; run="${jobs_run[$i]}"
    best="$OUT/$arm/run_$run/best_solution.json"
    if [[ -f "$best" ]]; then
      cost="$("$PY" -c 'import json,sys; print("%.5f" % json.load(open(sys.argv[1]))["evaluation"]["total_cost"])' "$best" 2>/dev/null)"
      [[ -z "$cost" ]] && cost="读取失败"
    else
      cost="缺失"
    fi
    printf '%-22s %s\n' "$arm/run_$run" "$cost"
  done
} >> "$BATCH_LOG"
log "汇总结束"
