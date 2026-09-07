#!/bin/zsh
# 2026-09-05 运行协议：M1 4 性能核，交付批 ≤3 并行、不降优先级（speed_diagnosis_20260905.md §3e）
# 表8（消融实验）干净重跑：三臂 × 10 次，冷启动、不注入任何已知解，自然停止（连续 20000 圈无改善）。
# 正式参数写死在 run_ablation_one.sh（碳价 0.2、endogenous、on_demand、registered、cost_plus_carbon、预筛开）。
# 工人池用 xargs -P（2026-09-02：zsh 的 wait -n 与子 shell 里的 jobs 都不可靠，前两次点火分别退化成 1 个和 24 个工人）。
# 用法：zsh solver/scripts/run_ablation_10x_clean.sh [并行工人数，默认 3] [输出根目录]
set -u
cd "$(dirname "$0")/../.."
REPO="$(pwd -P)"
WORKERS="${1:-3}"
OUT_ROOT="${2:-$REPO/solver/reports/ablation_formal_10x_20260902}"
mkdir -p "$OUT_ROOT"
JOBS="$OUT_ROOT/joblist.txt"
: > "$JOBS"
# 按"每轮一个三元组"排队：run_1 的三臂先跑，再 run_2……
for run in $(seq -w 1 10); do
  for arm in M-HGS MT-HGS MTC-HGS; do
    print -r -- "$arm|$run" >> "$JOBS"
  done
done
print "已排 $(wc -l < "$JOBS" | tr -d ' ') 个任务，输出根目录 $OUT_ROOT，并行 $WORKERS"
xargs -P "$WORKERS" -L 1 -I{} zsh "$REPO/solver/scripts/run_ablation_one.sh" "$OUT_ROOT" "{}" < "$JOBS"
print "全部任务结束：$OUT_ROOT"
