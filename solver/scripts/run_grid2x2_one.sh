#!/bin/zsh
# 2026-09-05 运行协议：M1 4 性能核，交付批 ≤3 并行、不降优先级（speed_diagnosis_20260905.md §3e）
# 二乘二格（日历 × 碳价）的补格批：run_grid2x2_one.sh <OUT_ROOT> "<CELL>|<ARM>|<run>"
#   CELL = beijing（北京真实日历 china81_runtime_parameter_authority_v4_20260723）
#          或 midday（午谷反事实日历 china81_cf_calendar_midday_valley_v1_20260904）
#   ARM  = MT-HGS（关闭充电择时，生效策略 asap）或 MTC-HGS（全机制，cost_plus_carbon）
#   run  = 两位数序号
# 碳价固定 1.0 元/kgCO2e（二乘二的高碳价那一列）。
# COMMON 参数与 run_ideal_construction_one.sh 逐条相同，只换日历与碳价，另加
# 2026-09-05 的新停机规则开关（连续两轮无改善才停；1 ＝ 历史行为）。
# 目录结构 <OUT_ROOT>/<CELL>/P=1.0/<ARM>/run_<kk>。
# 幂等：已有 best_solution.json 的跳过。
set -u
OUT_ROOT="$1"; job="$2"
cell="${job%%|*}"; rest="${job#*|}"; arm="${rest%%|*}"; run="${rest##*|}"
REPO="$(cd "$(dirname "$0")/../.." && pwd -P)"
cd "$REPO"
PY="$REPO/.public-hgs-venv/bin/python3"
export PYTHONPATH='solver/src:third_party/setp_hgs_kernel:models/src'
case "$cell" in
  beijing) CALENDAR=data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723 ;;
  midday)  CALENDAR=data/ChinaInstances/china81_cf_calendar_midday_valley_v1_20260904 ;;
  *) print "未知格 $cell"; exit 3 ;;
esac
price=1.0
dir="$OUT_ROOT/$cell/P=$price/$arm/run_$run"
if [[ -f "$dir/best_solution.json" ]]; then print "跳过 $cell/$arm/run_$run（已完成）"; exit 0; fi
mkdir -p "$OUT_ROOT/$cell/P=$price/$arm"
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
  --stop-after-nonimproving-rounds 2
  --tariff-calendar-authority "$CALENDAR"
)
case "$arm" in
  MT-HGS)  flags=(--mechanism-off charge_timing) ;;
  MTC-HGS) flags=() ;;
  *) print "未知臂 $arm"; exit 3 ;;
esac
print "[$(date +%H:%M:%S)] 启动 $cell/$arm/run_$run"
"$PY" solver/scripts/run_problem_hgs_private_technical.py \
    "$dir" --data-repo-root . --arm "$arm" "${COMMON[@]}" "${flags[@]}" \
    --carbon-price "$price" \
    >> "$OUT_ROOT/$cell/P=$price/$arm/run_$run.log" 2>&1
# `print "... exit=$?"` 里的 $? 会被同一 word 内的 $(date ...) 命令替换覆盖，
# 取到的是 date 的退出码。先存 rc 再打印。
rc=$?
print "[$(date +%H:%M:%S)] 完成 $cell/$arm/run_$run exit=$rc"
