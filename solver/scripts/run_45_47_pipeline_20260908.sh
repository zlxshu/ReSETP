#!/bin/zsh
# 2026-09-08：4.7 动态三臂 + 4.6 后半六个联盟，一条流水线跑完。
# 由 launchd 提交，脱离终端会话；带内存采样，便于判断进程消失是不是被系统杀的。
set -u
REPO="/Volumes/移动硬盘（512G）/ReSETP"
cd "$REPO"
PY="$REPO/.public-hgs-venv/bin/python3"
export PYTHONPATH='solver/src:third_party/setp_hgs_kernel:models/src'
MEMLOG="$REPO/solver/reports/pipeline_20260908_memory.log"

# 内存采样：每 30 秒记一次所有求解进程的常驻内存与系统可用内存
( while true; do
    ts=$(date "+%H:%M:%S")
    rss=$(ps -o rss=,command= -ax 2>/dev/null | grep -E "run_dynamic_experiment|run_coalition_experiment" | grep -v grep | awk '{s+=$1} END {printf "%.0f", s/1024}')
    free=$(vm_stat 2>/dev/null | awk '/Pages free/{f=$3} /Pages inactive/{i=$3} END {gsub(/\./,"",f); gsub(/\./,"",i); printf "%.0f", (f+i)*16384/1048576}')
    print "$ts 求解进程常驻内存=${rss:-0}MB 系统可用=${free:-?}MB" >> "$MEMLOG"
    sleep 30
  done ) &
MEMPID=$!
trap "kill $MEMPID 2>/dev/null" EXIT

print "[$(date +%H:%M:%S)] ===== 阶段一：4.7 动态三臂 ====="
"$PY" solver/scripts/run_dynamic_experiment.py \
    solver/reports/dynamic_v6_20260908 --data-repo-root . --carbon-price 0.2 \
    >> solver/reports/dynamic_v6_20260908_run4.log 2>&1
print "[$(date +%H:%M:%S)] 阶段一结束 exit=$?"

print "[$(date +%H:%M:%S)] ===== 阶段二：4.6 后半六个联盟 ====="
zsh solver/scripts/run_coalition_fs150_batch_20260908.sh \
    >> solver/reports/coalition_fs150_v6_20260908_batch.log 2>&1
print "[$(date +%H:%M:%S)] 阶段二结束 exit=$?"
print "[$(date +%H:%M:%S)] ===== 流水线全部结束 ====="
