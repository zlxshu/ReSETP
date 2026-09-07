#!/bin/zsh
# 2026-09-05 运行协议：M1 4 性能核，交付批 ≤3 并行、不降优先级（speed_diagnosis_20260905.md §3e）
# 三方案对比的单个任务：run_scheme_one.sh <OUT_ROOT> "<scheme>|<run>"
#   A  = 内核搜路线、精确账只算候选（--search-mode kernel_native），代理用"出发空档"替代按弧分摊
#   B  = 每个子代过精确账，但只对代理成本能进种群的子代算（--lazy-exact）
#   AB = 惰性精确账 + "出发空档"代理（integrated + --lazy-exact + gap proxy）
# 全部是全机制臂（MTC-HGS），正式参数与表8 交付批一致，自然停止。
set -u
OUT_ROOT="$1"; job="$2"
scheme="${job%%|*}"; run="${job##*|}"
REPO="$(cd "$(dirname "$0")/../.." && pwd -P)"
cd "$REPO"
PY="$REPO/.public-hgs-venv/bin/python3"
export PYTHONPATH='solver/src:third_party/setp_hgs_kernel:models/src'
dir="$OUT_ROOT/$scheme/run_$run"
if [[ -f "$dir/best_solution.json" ]]; then print "跳过 $scheme/run_$run（已完成）"; exit 0; fi
mkdir -p "$OUT_ROOT/$scheme"
COMMON=(
  --instance-id cn-jjj-50c-01-DEPOTSEARCH-d996f755bd
  --carbon-price 0.2
  --fleet-parameter-class endogenous
  --population-mode copied_hgs_defaults
  --recharge-mode on_demand
  --depot-curve registered
  --charge-timing-policy cost_plus_carbon
  --charging-prescreen
)
case "$scheme" in
  A)  flags=(--search-mode kernel_native --no-ev-charge-time-proxy --ev-departure-gap-proxy) ;;
  A3) flags=(--search-mode kernel_native --no-ev-charge-time-proxy --ev-departure-gap-proxy --confirming-round) ;;
  B)  flags=(--lazy-exact) ;;
  AB) flags=(--lazy-exact --no-ev-charge-time-proxy --ev-departure-gap-proxy) ;;
  *) print "未知方案 $scheme"; exit 3 ;;
esac
print "[$(date +%H:%M:%S)] 启动 $scheme/run_$run"
"$PY" solver/scripts/run_problem_hgs_private_technical.py \
    "$dir" --data-repo-root . --arm "MTC-HGS" "${COMMON[@]}" "${flags[@]}" \
    >> "$OUT_ROOT/$scheme/run_$run.log" 2>&1
# `print "... exit=$?"` 里的 $? 会被同一 word 内的 $(date ...) 命令替换覆盖，取到的是
# date 的退出码（见 comparison_n10/CONFIRM.md 的同类记录）。先存 rc 再打印。
rc=$?
print "[$(date +%H:%M:%S)] 完成 $scheme/run_$run exit=$rc"
