#!/bin/zsh
# 2026-09-06。两根杠杆的单个求解任务，一份 COMMON 参数：
#   run_lever_ctd_20260906_one.sh "<kind>|<value>|<run>"
#     kind=Q        免费碳配额（kg/日），落 solver/reports/lever_ctd_20260906/Q=<v>/run_<kk>
#     kind=premium  电动车日固定溢价（元/日），落
#                   solver/reports/lever_subsidy_20260904/premium=<v>/MTC-HGS/run_<kk>
#
# COMMON 逐条抄自 solver/scripts/run_lever_subsidy_one.sh（2026-09-04 补贴批），
# 另**显式**加 --stop-after-nonimproving-rounds 2。该值与今日默认值相同，写出来是为了
# 让 metadata 里留下痕迹：2026-09-04 那批跑在旧停机规则（等价于 1）下，与本批不同条件。
# 日历：不传 --tariff-calendar-authority，即北京现行电价日历。碳价固定 0.2，臂固定 MTC-HGS。
# 幂等：已有 best_solution.json 的跳过。
set -u
spec="$1"
kind="${spec%%|*}"; rest="${spec#*|}"; value="${rest%%|*}"; run="${rest##*|}"
REPO="$(cd "$(dirname "$0")/../.." && pwd -P)"
cd "$REPO"
PY="$REPO/.public-hgs-venv/bin/python3"
export PYTHONPATH='solver/src:third_party/setp_hgs_kernel:models/src:solver/scripts'

case "$kind" in
  Q)
    dir="solver/reports/lever_ctd_20260906/Q=$value/run_$run"
    log="solver/reports/lever_ctd_20260906/Q=$value/run_$run.log"
    LEVER=(--carbon-quota-kg "$value")
    ;;
  premium)
    dir="solver/reports/lever_subsidy_20260904/premium=$value/MTC-HGS/run_$run"
    log="solver/reports/lever_subsidy_20260904/premium=$value/MTC-HGS/run_$run.log"
    LEVER=(--ev-daily-premium "$value")
    ;;
  *) print "未知杠杆种类 $kind"; exit 3 ;;
esac

if [[ -f "$dir/best_solution.json" ]]; then
  print "[$(date +%H:%M:%S)] 跳过 $kind=$value/run_$run（已完成）"
  exit 0
fi
mkdir -p "$(dirname "$dir")"

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
)
print "[$(date +%H:%M:%S)] 启动 $kind=$value/run_$run"
"$PY" solver/scripts/run_problem_hgs_private_technical.py \
    "$dir" --data-repo-root . --arm "MTC-HGS" "${COMMON[@]}" \
    --carbon-price 0.2 \
    "${LEVER[@]}" \
    >> "$log" 2>&1
rc=$?
print "[$(date +%H:%M:%S)] 完成 $kind=$value/run_$run exit=$rc"
exit $rc
