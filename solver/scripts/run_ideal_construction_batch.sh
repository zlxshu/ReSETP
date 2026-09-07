#!/bin/zsh
# 2026-09-05 运行协议：M1 4 性能核，交付批 ≤3 并行、不降优先级（speed_diagnosis_20260905.md §3e）
# 理想条件构造批（E-B″）点火器：碳价 4 档 × 两臂 × 3 次 = 24 个任务。
# 求解一律在"午谷电价"反事实日历下进行（见 run_ideal_construction_one.sh）。
# 工人池用 xargs -P（zsh 的 wait -n / 子 shell jobs 不可靠，见 run_ablation_10x_clean.sh）。
# 用法：zsh solver/scripts/run_ideal_construction_batch.sh [并行工人数，默认 3] [输出根目录]
set -u
cd "$(dirname "$0")/../.."
REPO="$(pwd -P)"
WORKERS="${1:-3}"
OUT_ROOT="${2:-$REPO/solver/reports/ideal_construction_20260904}"
mkdir -p "$OUT_ROOT"
JOBS="$OUT_ROOT/joblist.txt"
: > "$JOBS"
for run in 01 02 03; do
  for price in 0.2 0.5 1.0 1.5; do
    for arm in MT-HGS MTC-HGS; do
      print -r -- "$price|$arm|$run" >> "$JOBS"
    done
  done
done
print "[$(date +%H:%M:%S)] E-B″ 理想条件构造批：$(wc -l < "$JOBS" | tr -d ' ') 任务，并行 $WORKERS，输出 $OUT_ROOT"
xargs -P "$WORKERS" -L 1 -I{} zsh "$REPO/solver/scripts/run_ideal_construction_one.sh" "$OUT_ROOT" "{}" < "$JOBS"
print "[$(date +%H:%M:%S)] E-B″ 批结束"
