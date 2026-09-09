#!/bin/zsh
# 2026-09-09：4.7 动态需求单跑（滚动臂开两处开关：候选预筛 + 逐客户兜底），等联盟批空出机器后再开。
set -u
REPO="/Volumes/移动硬盘（512G）/ReSETP"; cd "$REPO"
PY="$REPO/.public-hgs-venv/bin/python3"
export PYTHONPATH='solver/src:third_party/setp_hgs_kernel:models/src'
LOG="solver/reports/dynamic_v7_20260909_run1.log"
OUTDIR="solver/reports/dynamic_v7_20260909"
PAT='run_coalition_experi[m]ent.py'   # 方括号避免 pgrep 匹配到本脚本自身
if pgrep -f "$PAT" >/dev/null; then
  print "[$(date +%H:%M:%S)] 等待联盟批结束" >> "$LOG"
  while pgrep -f "$PAT" >/dev/null; do sleep 60; done
fi
print "[$(date +%H:%M:%S)] 联盟批已空，启动 dynamic v7" >> "$LOG"
"$PY" solver/scripts/run_dynamic_experiment.py "$OUTDIR" --data-repo-root . --carbon-price 0.2 \
    --prefilter-ineligible-assets --partial-fallback >> "$LOG" 2>&1
print "[$(date +%H:%M:%S)] dynamic v7 exit=$?" >> "$LOG"
