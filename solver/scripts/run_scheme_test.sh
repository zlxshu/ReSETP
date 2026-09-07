#!/bin/zsh
# 2026-09-05 运行协议：M1 4 性能核，交付批 ≤3 并行、不降优先级（speed_diagnosis_20260905.md §3e）
# 三方案 × 3 次（全机制臂）对比：zsh solver/scripts/run_scheme_test.sh [工人数=3] [输出根目录]
set -u
cd "$(dirname "$0")/../.."
REPO="$(pwd -P)"
WORKERS="${1:-3}"
OUT_ROOT="${2:-$REPO/solver/reports/scheme_test_20260903}"
mkdir -p "$OUT_ROOT"
JOBS="$OUT_ROOT/joblist.txt"; : > "$JOBS"
for run in 1 2 3; do for scheme in A B AB; do print -r -- "$scheme|$run" >> "$JOBS"; done; done
print "已排 $(wc -l < "$JOBS" | tr -d ' ') 个任务，输出 $OUT_ROOT，并行 $WORKERS"
xargs -P "$WORKERS" -L 1 -I{} zsh "$REPO/solver/scripts/run_scheme_one.sh" "$OUT_ROOT" "{}" < "$JOBS"
print "全部任务结束：$OUT_ROOT"
