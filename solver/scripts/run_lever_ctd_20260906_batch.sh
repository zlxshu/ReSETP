#!/bin/zsh
# 2026-09-06 批：碳配额 Q∈{0,200} 各 3 次 + 购置补贴档 premium=76 3 次 = 9 个求解。
# Q=0 必须与 Q=200 同批同规则跑：2026-09-04 那批用的是旧停机规则，直接拿它当基准
# 会把搜索深度差算到配额头上（配额的预期效应是零，任何差都会被误读）。
# 运行协议：M1 4 性能核，≤3 并行，不降优先级。
set -u
cd "$(dirname "$0")/../.."
REPO="$(pwd -P)"
WORKERS="${1:-3}"
OUT="$REPO/solver/reports/lever_ctd_20260906"
mkdir -p "$OUT"
JOBS="$OUT/joblist.txt"
: > "$JOBS"
for run in 01 02 03; do
  for q in 0 200; do print -r -- "Q|$q|$run" >> "$JOBS"; done
done
for run in 01 02 03; do print -r -- "premium|76|$run" >> "$JOBS"; done
print "[$(date +%H:%M:%S)] 杠杆批：$(wc -l < "$JOBS" | tr -d ' ') 任务，并行 $WORKERS"
xargs -P "$WORKERS" -L 1 -I{} zsh "$REPO/solver/scripts/run_lever_ctd_20260906_one.sh" {} < "$JOBS"
print "[$(date +%H:%M:%S)] 杠杆批结束"
