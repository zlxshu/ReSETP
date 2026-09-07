#!/bin/zsh
# 2026-09-05 运行协议：M1 4 性能核，交付批 ≤3 并行、不降优先级（speed_diagnosis_20260905.md §3e）
# 绿色充电窗口补贴杠杆（表11 新增行）的单个任务：
#   run_lever_green_window_one.sh <OUT_ROOT> "<run>"
#   run = 两位数序号（01/02/03）
# 日历：--tariff-calendar-authority 指向
#   data/ChinaInstances/china81_cf_calendar_midday_discount_v1_20260904
#   （北京现行分时电价一个字不动，只把 12:00–15:00 六个半小时槽的电度价按谷价
#     0.56328575 元/kWh 计，差价由财政补贴；见该目录 README）。
# COMMON 参数与 run_ideal_construction_one.sh 的 MTC-HGS 臂逐条相同（全机制，
#   flags 为空），碳价固定 0.2，臂固定 MTC-HGS。
# 目录结构 <OUT_ROOT>/MTC-HGS/run_<kk>（没有 P=<p> 那一层）。
# 幂等：已有 best_solution.json 的跳过。
set -u
OUT_ROOT="$1"; run="$2"
REPO="$(cd "$(dirname "$0")/../.." && pwd -P)"
cd "$REPO"
PY="$REPO/.public-hgs-venv/bin/python3"
export PYTHONPATH='solver/src:third_party/setp_hgs_kernel:models/src'
CALENDAR=data/ChinaInstances/china81_cf_calendar_midday_discount_v1_20260904
dir="$OUT_ROOT/MTC-HGS/run_$run"
if [[ -f "$dir/best_solution.json" ]]; then print "跳过 run_$run（已完成）"; exit 0; fi
mkdir -p "$OUT_ROOT/MTC-HGS"
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
  --tariff-calendar-authority "$CALENDAR"
)
print "[$(date +%H:%M:%S)] 启动 green_window/run_$run"
"$PY" solver/scripts/run_problem_hgs_private_technical.py \
    "$dir" --data-repo-root . --arm "MTC-HGS" "${COMMON[@]}" \
    --carbon-price 0.2 \
    >> "$OUT_ROOT/MTC-HGS/run_$run.log" 2>&1
rc=$?
print "[$(date +%H:%M:%S)] 完成 green_window/run_$run exit=$rc"
