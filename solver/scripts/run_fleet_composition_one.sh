#!/bin/zsh
# 表9（动力配置）全方案固定配比的单个子跑：run_fleet_composition_one.sh <OUT_ROOT> "<A_cv>/<A_ev>|<B_cv>/<B_ev>|<run>"
#   一档＝全方案 k 油 / (N−k) 电（所有车场之和）；车场分法按枚举逐个跑，每档取全部分法里最好的。
#   A＝D_OSM_WAY_1003511503，B＝D_OSM_WAY_1071205721；某车场可为 0/0。
#   与表8/表11 入口的差别只有 --ev-reload-gap-proxy（替换 --ev-departure-gap-proxy）和车队写死；
#   幂等：已有 best_solution.json 的跳过。
set -u
OUT_ROOT="$1"; job="$2"
a="${job%%|*}"; rest="${job#*|}"; b="${rest%%|*}"; run="${rest##*|}"
REPO="$(cd "$(dirname "$0")/../.." && pwd -P)"; cd "$REPO"
PY="$REPO/.public-hgs-venv/bin/python3"
export PYTHONPATH='solver/src:third_party/setp_hgs_kernel:models/src'
a_cv="${a%%/*}"; a_ev="${a##*/}"; b_cv="${b%%/*}"; b_ev="${b##*/}"
rung="$((a_cv + b_cv))-$((a_ev + b_ev))"
tag="A${a_cv}-${a_ev}_B${b_cv}-${b_ev}"
dir="$OUT_ROOT/$rung/$tag/run_$run"
if [[ -f "$dir/best_solution.json" ]]; then print "跳过 $rung/$tag/run_$run"; exit 0; fi
mkdir -p "$OUT_ROOT/$rung/$tag"
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
print "[$(date +%H:%M:%S)] 启动 $rung/$tag/run_$run"
nice -n 5 "$PY" solver/scripts/run_problem_hgs_private_technical.py \
    "$dir" --data-repo-root . --arm "MTC-HGS" "${COMMON[@]}" \
    --fleet-mix-override "D_OSM_WAY_1003511503=${a_cv}/${a_ev},D_OSM_WAY_1071205721=${b_cv}/${b_ev}" \
    >> "$OUT_ROOT/$rung/$tag/run_$run.log" 2>&1
print "[$(date +%H:%M:%S)] 完成 $rung/$tag/run_$run exit=$?"
