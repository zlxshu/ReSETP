#!/bin/zsh
# 2026-09-05 运行协议：M1 4 性能核，交付批 ≤3 并行、不降优先级（speed_diagnosis_20260905.md §3e）
# 电动车补贴杠杆（表11 新增行）的单个任务：
#   run_lever_subsidy_one.sh <OUT_ROOT> "<premium>|<run>"
#   premium = 电动车相对燃油车的日固定溢价（元/天）；基准 100（现行车辆权威值），
#             50 = 补贴一半，0 = 电油同价。溢价通过 --ev-daily-premium 传入，
#             runner 据此把 EV 日固定成本改写为 CV + premium，
#             代理（kernel_proposals）与精确账（cost.py）同时看到。
#   run     = 两位数序号（01/02/03）
# 日历：**不传** --tariff-calendar-authority，即北京现行电价日历（与基准
#   ablation_formal_10x_v5_20260904 / private_axes_formal_v2_20260904 同一份）。
# COMMON 参数与 run_private_axes_one.sh 逐条相同；碳价固定 0.2，臂固定 MTC-HGS。
# 目录结构 <OUT_ROOT>/premium=<v>/MTC-HGS/run_<kk>。
# 幂等：已有 best_solution.json 的跳过。
set -u
OUT_ROOT="$1"; job="$2"
premium="${job%%|*}"; run="${job##*|}"
REPO="$(cd "$(dirname "$0")/../.." && pwd -P)"
cd "$REPO"
PY="$REPO/.public-hgs-venv/bin/python3"
export PYTHONPATH='solver/src:third_party/setp_hgs_kernel:models/src'
dir="$OUT_ROOT/premium=$premium/MTC-HGS/run_$run"
if [[ -f "$dir/best_solution.json" ]]; then print "跳过 premium=$premium/run_$run（已完成）"; exit 0; fi
mkdir -p "$OUT_ROOT/premium=$premium/MTC-HGS"
COMMON=(
  --instance-id cn-jjj-50c-01-DEPOTSEARCH-d996f755bd
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
print "[$(date +%H:%M:%S)] 启动 premium=$premium/run_$run"
"$PY" solver/scripts/run_problem_hgs_private_technical.py \
    "$dir" --data-repo-root . --arm "MTC-HGS" "${COMMON[@]}" \
    --carbon-price 0.2 \
    --ev-daily-premium "$premium" \
    >> "$OUT_ROOT/premium=$premium/MTC-HGS/run_$run.log" 2>&1
rc=$?
print "[$(date +%H:%M:%S)] 完成 premium=$premium/run_$run exit=$rc"
