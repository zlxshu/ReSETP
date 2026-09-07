#!/bin/zsh
# 2026-09-05 运行协议：M1 4 性能核，交付批 ≤3 并行、不降优先级（speed_diagnosis_20260905.md §3e）
# 表11 两根新杠杆（电动车补贴 / 企业作业时间窗）的点火器。
# 用法：zsh solver/scripts/run_lever_batch.sh <阶段> [并行工人数，默认 3]
#   阶段 phase1 = 复制通道恒等探针 1 跑 + 补贴档 premium∈{50,0} × 3 次 = 7 个任务
#   阶段 phase2 = 作业时间窗 lunch1114 × 3 次 = 3 个任务（须在探针通过、
#                 且副本的 shift_contract.json / orders.csv 已改好之后再跑）
# 工人池用 xargs -P（zsh 的 wait -n / 子 shell jobs 不可靠）。
set -u
cd "$(dirname "$0")/../.."
REPO="$(pwd -P)"
PHASE="${1:?用法：run_lever_batch.sh <phase1|phase2> [workers]}"
WORKERS="${2:-3}"
SUB_ROOT="$REPO/solver/reports/lever_subsidy_20260904"
WIN_ROOT="$REPO/solver/reports/lever_workwindow_20260904"
mkdir -p "$SUB_ROOT" "$WIN_ROOT"
JOBS="$WIN_ROOT/joblist_$PHASE.txt"
: > "$JOBS"
case "$PHASE" in
  phase1)
    print -r -- "W|probe_identity|01" >> "$JOBS"
    for run in 01 02 03; do
      for premium in 50 0; do
        print -r -- "S|$premium|$run" >> "$JOBS"
      done
    done
    ;;
  phase2)
    for run in 01 02 03; do
      print -r -- "W|lunch1114|$run" >> "$JOBS"
    done
    ;;
  *) print "未知阶段 $PHASE"; exit 3 ;;
esac
print "[$(date +%H:%M:%S)] 表11 杠杆批 $PHASE：$(wc -l < "$JOBS" | tr -d ' ') 任务，并行 $WORKERS"
xargs -P "$WORKERS" -L 1 -I{} zsh -c '
  REPO="$0"; SUB_ROOT="$1"; WIN_ROOT="$2"; spec="$3"
  kind="${spec%%|*}"; rest="${spec#*|}"
  case "$kind" in
    S) zsh "$REPO/solver/scripts/run_lever_subsidy_one.sh" "$SUB_ROOT" "$rest" ;;
    W) zsh "$REPO/solver/scripts/run_lever_workwindow_one.sh" "$WIN_ROOT" "$rest" ;;
    *) print "未知任务种类 $kind"; exit 3 ;;
  esac
' "$REPO" "$SUB_ROOT" "$WIN_ROOT" {} < "$JOBS"
print "[$(date +%H:%M:%S)] 表11 杠杆批 $PHASE 批结束"
