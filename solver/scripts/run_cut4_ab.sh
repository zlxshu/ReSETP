#!/bin/zsh
# 2026-09-05 运行协议：M1 4 性能核，交付批 ≤3 并行、不降优先级（speed_diagnosis_20260905.md §3e）
# 第四刀对照：旧版（三刀完成态快照）对 新版（当前工作树），按原版 HGS 停止规则
# ——连续 20,000 圈无改善即停——各跑到自然停止，不设任何墙钟。比最终解成本、停在第几圈、
# 子代存活率、最终解是否仍完成 50 客户且零违规。
#
# 用法：zsh solver/scripts/run_cut4_ab.sh [每版重复次数，默认 3] [并行工人数，默认 3]
set -u
cd "$(dirname "$0")/../.."
REPO="$(pwd -P)"
REPEATS="${1:-3}"
WORKERS="${2:-3}"
PY="$REPO/.public-hgs-venv/bin/python3"
OLD_SRC="$REPO/solver/reports/solver_speed_cuts_20260902/frozen_three_cuts"
OUT_ROOT="$REPO/solver/reports/cut4_admission_ab_20260902"
mkdir -p "$OUT_ROOT"
COMMON=(
  --data-repo-root "$REPO"
  --instance-id cn-jjj-50c-01-DEPOTSEARCH-d996f755bd
  --carbon-price 0.2
  --fleet-parameter-class endogenous
  --population-mode copied_hgs_defaults
  --recharge-mode on_demand
  --depot-curve registered
  --charge-timing-policy cost_plus_carbon
  --charging-prescreen
)
JOBS="$OUT_ROOT/joblist.txt"; : > "$JOBS"
for r in $(seq -w 1 "$REPEATS"); do
  print -r -- "old|$OLD_SRC/src|$OLD_SRC/scripts|$r" >> "$JOBS"
  print -r -- "new|$REPO/solver/src|$REPO/solver/scripts|$r" >> "$JOBS"
done
run_one() {
  local label="${1%%|*}" rest="${1#*|}"
  local src="${rest%%|*}"; rest="${rest#*|}"
  local scripts="${rest%%|*}"; local run="${rest#*|}"
  local dir="$OUT_ROOT/$label/run_$run"
  [[ -f "$dir/best_solution.json" ]] && { print "跳过 $label/run_$run"; return 0; }
  # 求解器拒绝写入已存在的目录，输出目录由它自己创建；日志放在旁边。
  mkdir -p "$OUT_ROOT/$label"
  print "[$(date +%H:%M:%S)] 启动 $label/run_$run"
  env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$src:$REPO/third_party/setp_hgs_kernel:$REPO/models/src" \
    "$PY" "$scripts/run_problem_hgs_private_technical.py" "$dir" \
      "${COMMON[@]}" --arm "cut4_$label" --convergence-csv "$dir/conv.csv" \
      >> "$dir.stdout.log" 2>&1
  # `print "... exit=$?"` 里的 $? 会被同一 word 内的 $(date ...) 命令替换覆盖，取到的是
  # date 的退出码（见 comparison_n10/CONFIRM.md 的同类记录）。先存 rc 再打印。
  rc=$?
  print "[$(date +%H:%M:%S)] 结束 $label/run_$run exit=$rc"
}
integer running=0
while read -r job; do
  run_one "$job" &
  (( running += 1 ))
  if (( running >= WORKERS )); then wait -n 2>/dev/null || wait; (( running -= 1 )); fi
done < "$JOBS"
wait
print "CUT4_AB_DONE $OUT_ROOT"
