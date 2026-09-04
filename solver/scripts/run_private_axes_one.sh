#!/bin/zsh
# 私有算例两条轴的单个任务（方案 A3 正式入口）：run_private_axes_one.sh <OUT_ROOT> "<axis>|<level>|<run>"
#   axis=carbon : level=碳价（元/kg），全机制臂，表11
#   axis=mix    : level=每车场 油/电 车数（如 4/2），全机制臂，表9（两车场同构成，用户令对称梯度）
set -u
OUT_ROOT="$1"; job="$2"
axis="${job%%|*}"; rest="${job#*|}"; level="${rest%%|*}"; run="${rest##*|}"
REPO="$(cd "$(dirname "$0")/../.." && pwd -P)"; cd "$REPO"
PY="$REPO/.public-hgs-venv/bin/python3"
export PYTHONPATH='solver/src:third_party/setp_hgs_kernel:models/src'
tag="${level//\//-}"
dir="$OUT_ROOT/$axis/$tag/run_$run"
if [[ -f "$dir/best_solution.json" ]]; then print "跳过 $axis/$tag/run_$run"; exit 0; fi
mkdir -p "$OUT_ROOT/$axis/$tag"
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
  # 2026-09-03 晚用户令"肯定翻"：充电预留改为"回场副本"口径（全局默认），见 fleet_composition_probe_20260903/README.md
  --ev-reload-gap-proxy
  --confirming-round
)
case "$axis" in
  carbon) flags=(--carbon-price "$level") ;;
  mix)    flags=(--carbon-price 0.2 --fleet-mix-override "D_OSM_WAY_1003511503=$level,D_OSM_WAY_1071205721=$level") ;;
  *) print "未知轴 $axis"; exit 3 ;;
esac
print "[$(date +%H:%M:%S)] 启动 $axis/$tag/run_$run"
nice -n 5 "$PY" solver/scripts/run_problem_hgs_private_technical.py \
    "$dir" --data-repo-root . --arm "MTC-HGS" "${COMMON[@]}" "${flags[@]}" \
    >> "$OUT_ROOT/$axis/$tag/run_$run.log" 2>&1
print "[$(date +%H:%M:%S)] 完成 $axis/$tag/run_$run exit=$?"
