#!/bin/zsh
# 2026-09-05 二乘二补格批点火器。用法：
#   zsh solver/scripts/run_grid2x2_batch.sh <joblist 文件> [并行工人数，默认 3] [输出根目录]
# 工人池用 xargs -P（zsh 的 wait -n / 子 shell jobs 不可靠，见 run_ablation_10x_clean.sh）。
set -u
cd "$(dirname "$0")/../.."
REPO="$(pwd -P)"
JOBS="$1"
WORKERS="${2:-3}"
OUT_ROOT="${3:-$REPO/solver/reports/grid2x2_20260905}"
mkdir -p "$OUT_ROOT"
print "[$(date +%H:%M:%S)] 二乘二补格批：$(wc -l < "$JOBS" | tr -d ' ') 任务，并行 $WORKERS，输出 $OUT_ROOT"
xargs -P "$WORKERS" -L 1 -I{} zsh "$REPO/solver/scripts/run_grid2x2_one.sh" "$OUT_ROOT" "{}" < "$JOBS"
print "[$(date +%H:%M:%S)] 二乘二补格批结束"
