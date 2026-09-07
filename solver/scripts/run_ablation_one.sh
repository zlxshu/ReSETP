#!/bin/zsh
# 2026-09-05 运行协议：M1 4 性能核，交付批 ≤3 并行、不降优先级（speed_diagnosis_20260905.md §3e）
# 表8 交付批的单个任务：run_ablation_one.sh <OUT_ROOT> "<arm>|<run>"
# 幂等：已有 best_solution.json 的跳过；求解器自己创建输出目录（已存在会拒绝）。
# DRY_RUN=1 时只睡 2 秒，用于验证工人池并发上限。
set -u
OUT_ROOT="$1"; job="$2"
arm="${job%%|*}"; run="${job##*|}"
REPO="$(cd "$(dirname "$0")/../.." && pwd -P)"
cd "$REPO"
PY="$REPO/.public-hgs-venv/bin/python3"
export PYTHONPATH='solver/src:third_party/setp_hgs_kernel:models/src'
dir="$OUT_ROOT/$arm/run_$run"
if [[ -f "$dir/best_solution.json" ]]; then print "跳过 $arm/run_$run（已完成）"; exit 0; fi
mkdir -p "$OUT_ROOT/$arm"
COMMON=(
  --instance-id cn-jjj-50c-01-DEPOTSEARCH-d996f755bd
  --carbon-price 0.2
  --fleet-parameter-class endogenous
  --population-mode copied_hgs_defaults
  --recharge-mode on_demand
  --depot-curve registered
  --charge-timing-policy cost_plus_carbon
  --charging-prescreen
  # 2026-09-03 用户定：算法＝方案 A（内核搜路线、精确账只算内核种群候选、电价回填再搜）。
  # 2026-09-03 晚用户令"肯定翻"：充电预留改为"回场副本"口径（首趟不扣、趟间按最长趟并逐轮按实际回填），
  # 与精确账"车可在车场等充电再走"的模型对齐一起成为全局默认；证据 solver/reports/fleet_composition_probe_20260903/README.md。
  --search-mode kernel_native
  --no-ev-charge-time-proxy
  --ev-reload-gap-proxy
  --confirming-round
)
case "$arm" in
  M-HGS)   flags=(--mechanism-off charge_timing,type_exchange) ;;
  MT-HGS)  flags=(--mechanism-off charge_timing) ;;
  MTC-HGS) flags=() ;;
  *) print "未知臂 $arm"; exit 3 ;;
esac
if [[ "${DRY_RUN:-0}" == "1" ]]; then print "[$(date +%H:%M:%S)] DRY $arm/run_$run"; sleep 2; exit 0; fi
print "[$(date +%H:%M:%S)] 启动 $arm/run_$run"
"$PY" solver/scripts/run_problem_hgs_private_technical.py \
    "$dir" --data-repo-root . --arm "$arm" "${COMMON[@]}" "${flags[@]}" \
    >> "$OUT_ROOT/$arm/run_$run.log" 2>&1
# `print "... exit=$?"` 里的 $? 会被同一 word 内的 $(date ...) 命令替换覆盖，取到的是
# date 的退出码（见 comparison_n10/CONFIRM.md 的同类记录）。先存 rc 再打印。
rc=$?
print "[$(date +%H:%M:%S)] 完成 $arm/run_$run exit=$rc"
