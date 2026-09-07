#!/bin/zsh
# 2026-09-05 运行协议：M1 4 性能核，交付批 ≤3 并行、不降优先级（speed_diagnosis_20260905.md §3e）
# 理想条件构造批的热启动跑：run_ideal_construction_warm_one.sh <OUT_ROOT> "<P>|<run>"
#   P   = 碳价（元/kgCO2e）
#   run = 两位数序号（01..10）
# 臂固定为 MTC-HGS-warm：与 run_ideal_construction_one.sh 的 MTC-HGS 臂逐条相同的参数
# （同一个 COMMON 数组、同一个午谷电价日历、flags 同样为空），**只多一个
# --initial-solution**：把 MT-HGS 第 <run> 次的路线按 cost_plus_carbon 重排后的解
# （臂②，由 build_charge_timing_comparison.py --dump-resettled-dir 落盘）作为初始解喂进去。
# 检验的问题：全优化能否在"只改充电时刻"的方案基础上再降。
# 初始解路径：<OUT_ROOT>/P=<p>/comparison_n10_dump/resettled/MT-HGS/run_<kk>/cost_plus_carbon.json
# 产物目录：  <OUT_ROOT>/P=<p>/MTC-HGS-warm/run_<kk>
# 幂等：已有 best_solution.json 的跳过。
set -u
OUT_ROOT="$1"; job="$2"
price="${job%%|*}"; run="${job##*|}"
arm=MTC-HGS-warm
REPO="$(cd "$(dirname "$0")/../.." && pwd -P)"
cd "$REPO"
PY="$REPO/.public-hgs-venv/bin/python3"
export PYTHONPATH='solver/src:third_party/setp_hgs_kernel:models/src'
CALENDAR=data/ChinaInstances/china81_cf_calendar_midday_valley_v1_20260904
INIT="$OUT_ROOT/P=$price/comparison_n10_dump/resettled/MT-HGS/run_$run/cost_plus_carbon.json"
dir="$OUT_ROOT/P=$price/$arm/run_$run"
if [[ -f "$dir/best_solution.json" ]]; then print "跳过 P=$price/$arm/run_$run（已完成）"; exit 0; fi
if [[ ! -f "$INIT" ]]; then print "缺初始解 $INIT"; exit 4; fi
mkdir -p "$OUT_ROOT/P=$price/$arm"
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
# MTC-HGS 臂：mechanism_off 为空，与冷启动臂一致。
flags=()
print "[$(date +%H:%M:%S)] 启动 P=$price/$arm/run_$run（初始解 $INIT）"
"$PY" solver/scripts/run_problem_hgs_private_technical.py \
    "$dir" --data-repo-root . --arm MTC-HGS "${COMMON[@]}" "${flags[@]}" \
    --carbon-price "$price" \
    --initial-solution "$INIT" \
    >> "$OUT_ROOT/P=$price/$arm/run_$run.log" 2>&1
# `print "... exit=$?"` 里的 $? 会被同一 word 内的 $(date ...) 命令替换覆盖，取到的是
# date 的退出码（见 comparison_n10/CONFIRM.md 的同类记录）。先存 rc 再打印。
rc=$?
print "[$(date +%H:%M:%S)] 完成 P=$price/$arm/run_$run exit=$rc"
exit "$rc"
