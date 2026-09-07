#!/bin/zsh
# 2026-09-05 运行协议：M1 4 性能核，交付批 ≤3 并行、不降优先级（speed_diagnosis_20260905.md §3e）
# 理想条件构造批（E-B″）的单个任务：run_ideal_construction_one.sh <OUT_ROOT> "<P>|<ARM>|<run>"
#   P    = 碳价（元/kgCO2e）
#   ARM  = MT-HGS（关闭充电择时，生效策略 asap）或 MTC-HGS（全机制，cost_plus_carbon）
#   run  = 两位数序号（01/02/03）
# 求解在"午谷电价"反事实日历下进行：--tariff-calendar-authority 指向 midday_valley 目录。
# COMMON 参数与 run_private_axes_one.sh / run_ablation_one.sh 逐条相同（正式口径）。
# 目录结构 <OUT_ROOT>/P=<p>/<ARM>/run_<kk>，每个 P=<p>/ 目录即一个可直接喂给
# build_charge_timing_comparison.py --batch-dir 的批次。
# 幂等：已有 best_solution.json 的跳过。
set -u
OUT_ROOT="$1"; job="$2"
price="${job%%|*}"; rest="${job#*|}"; arm="${rest%%|*}"; run="${rest##*|}"
REPO="$(cd "$(dirname "$0")/../.." && pwd -P)"
cd "$REPO"
PY="$REPO/.public-hgs-venv/bin/python3"
export PYTHONPATH='solver/src:third_party/setp_hgs_kernel:models/src'
CALENDAR=data/ChinaInstances/china81_cf_calendar_midday_valley_v1_20260904
dir="$OUT_ROOT/P=$price/$arm/run_$run"
if [[ -f "$dir/best_solution.json" ]]; then print "跳过 P=$price/$arm/run_$run（已完成）"; exit 0; fi
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
case "$arm" in
  MT-HGS)  flags=(--mechanism-off charge_timing) ;;
  MTC-HGS) flags=() ;;
  *) print "未知臂 $arm"; exit 3 ;;
esac
print "[$(date +%H:%M:%S)] 启动 P=$price/$arm/run_$run"
"$PY" solver/scripts/run_problem_hgs_private_technical.py \
    "$dir" --data-repo-root . --arm "$arm" "${COMMON[@]}" "${flags[@]}" \
    --carbon-price "$price" \
    >> "$OUT_ROOT/P=$price/$arm/run_$run.log" 2>&1
# `print "... exit=$?"` 里的 $? 会被同一 word 内的 $(date ...) 命令替换覆盖，取到的是
# date 的退出码（见 comparison_n10/CONFIRM.md 的同类记录）。先存 rc 再打印。
rc=$?
print "[$(date +%H:%M:%S)] 完成 P=$price/$arm/run_$run exit=$rc"
