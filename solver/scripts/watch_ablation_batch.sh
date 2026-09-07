#!/bin/zsh
# 表8 交付批哨兵：每 INTERVAL 秒写一行到 $OUT/watchdog.log。
# 五类信号：完成（best_solution.json 数=任务数）、停工（存活求解器 0 且未完成）、
# 空转/停滞（进程在但某跑的 conv.csv 超过 STALL 秒没变且未落盘）、产物计数、内存压力。
# 用法：zsh solver/scripts/watch_ablation_batch.sh <OUT_ROOT> [interval=600] [stall=3600]
set -u
OUT="$1"; INTERVAL="${2:-600}"; STALL="${3:-3600}"
LOG="$OUT/watchdog.log"
JOBS="$OUT/joblist.txt"
TICK=0
while true; do
  now=$(date +%s); TICK=$((TICK+1))
  total=$(wc -l < "$JOBS" 2>/dev/null | tr -d ' ')
  done_n=$(find "$OUT" -name best_solution.json -path "*/run_*" -not -path "*_invalid*" | wc -l | tr -d ' ')
  alive=$(pgrep -f "run_problem_hgs_private_technical.py" | wc -l | tr -d ' ')
  mem=$(vm_stat | awk '/Pages free/{f=$3} /Pages active/{a=$3} /Pages speculative/{s=$3} END{gsub(/\./,"",f); printf "free=%dMB", (f+0)*4096/1048576}')
  swap=$(sysctl -n vm.swapusage 2>/dev/null | awk '{print "swap_used="$7}')
  line="[$(date +%H:%M:%S)] 完成=$done_n/$total 存活求解器=$alive $mem $swap"
  stalled=0
  for conv in $(find "$OUT" -name convergence.csv -path "*/run_*" -not -path "*_invalid*" 2>/dev/null | sort); do
    dir=$(dirname "$conv")
    [[ -f "$dir/best_solution.json" ]] && continue
    last=$(tail -1 "$conv" 2>/dev/null)
    cyc=$(echo "$last" | cut -d, -f1); cost=$(echo "$last" | cut -d, -f5 | cut -c1-8)
    mtime=$(stat -f %m "$conv"); age=$((now-mtime))
    flag=""; if (( age > STALL )); then flag=" ⚠停滞"; stalled=$((stalled+1)); fi
    line="$line | $(basename $(dirname $dir))/$(basename $dir) 圈=$cyc 成本=$cost 距上次${age}s$flag"
  done
  if (( done_n >= total && total > 0 )); then
    echo "$line | ✅ 全部完成" >> "$LOG"; echo "ABLATION_BATCH_DONE" >> "$LOG"; exit 0
  fi
  # 前两次巡检给工人启动留出时间，不把"还没起来"当停工。
  if (( alive == 0 && ${TICK:-0} >= 2 )); then
    echo "$line | ❌ 停工：没有存活求解器但未完成" >> "$LOG"; echo "ABLATION_BATCH_HALT" >> "$LOG"; exit 2
  fi
  if (( stalled > 0 )); then echo "$line | ⚠ 有 $stalled 个跑超过 ${STALL}s 无进展" >> "$LOG"; else echo "$line" >> "$LOG"; fi
  sleep "$INTERVAL"
done
