#!/bin/zsh
# 2026-09-09：修补四家企业联盟成本表里的"联盟比拆开还贵"。
#
# 这种反常不是经济现象，是那一格的搜索没找到解：把联盟拆成几块分别跑再拼起来，
# 就是该联盟的一个可行解，所以联盟成本不可能真的更高。做法是拿"最优拆分各块已存
# 结果"的并集当起手解重跑该联盟，跑进新目录（旧结果不覆盖，成本取两边更小的）。
#
# 先等机器空下来（另外三条实验在跑），最多补两轮，每轮最多 3 个并行。
# 环境变量 RESEED_DRY_RUN=1：不等待、不跑求解器，只把这一轮会执行的命令打印出来。
set -u

REPO="/Volumes/移动硬盘（512G）/ReSETP"
cd "$REPO" || exit 1
PY="$REPO/.public-hgs-venv/bin/python3"
export PYTHONPATH='solver/src:third_party/setp_hgs_kernel:models/src'

OUT="solver/reports/coalition_fs150_v6_20260908"
PKG="data/ChinaInstances/china81_final_suite_v2_20260815"
INST="cn-prd-150c-01-V3-TWO-SHIFT-FS"
LOG="solver/reports/coalition_fs150_v6_20260908_batch.log"
ALLOC="solver/scripts/coalition_allocation_four_firm.py"
FINAL_JSON="$OUT/allocation_four_firm_final.json"
MAX_ROUNDS=2
PAR=3
DRY="${RESEED_DRY_RUN:-0}"

log() { print -r -- "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG" }

# 所有已存在的补跑轮次目录都参与取最小值；还没建的轮次不传（脚本里也跳过）。
build_extra() {
  EXTRA=()
  local d
  for d in "$OUT"/reseed_r*(N/); do
    EXTRA+=(--extra-root "$d")
  done
}

# 三条正在跑的实验都结束才动手；方括号写法让 pgrep 不会匹配到本脚本自己。
wait_for_idle() {
  local busy
  while true; do
    busy=0
    pgrep -f 'run_problem_hgs_private_technica[l].py' >/dev/null 2>&1 && busy=1
    pgrep -f 'run_dynamic_experimen[t].py' >/dev/null 2>&1 && busy=1
    pgrep -f 'run_coalition_experi[m]ent.py' >/dev/null 2>&1 && busy=1
    if (( busy == 0 )); then
      log "机器已空闲，开始补跑"
      return 0
    fi
    log "等待：仍有实验在跑，60 秒后再看"
    sleep 60
  done
}

# 写出一份补跑清单，回显里含 "RESEED <目录名> <企业列表> <种子目录列表>" 行。
# 返回违反条数；清单读不出来（例如 15 格没凑齐）时返回 255。
make_plan() {
  local pf="$1"
  build_extra
  "$PY" "$ALLOC" --root "$OUT" "${EXTRA[@]}" --print-reseed-plan > "$pf" 2>&1
  local n
  n=$(sed -n 's/^RESEED_COUNT //p' "$pf" | tail -1)
  if [[ -z "$n" ]]; then
    log "算不出分摊：$pf 里没有 RESEED_COUNT，末尾内容如下"
    tail -5 "$pf" | tee -a "$LOG"
    return 255
  fi
  return "$n"
}

run_one() {
  local tag="$1" members="$2" seeds="$3" rdir="$4" rc
  mkdir -p "$rdir"
  log "启动 $tag 企业=$members"
  "$PY" solver/scripts/run_coalition_experiment.py \
      --instance-id "$INST" --package "$PKG" \
      --coalition "$members" --output-dir "$rdir" \
      --seed-from-dirs "$seeds" >> "$rdir/$tag.log" 2>&1
  rc=$?
  log "完成 $tag exit=$rc"
}

log "===== 联盟成本补跑开始（最多 $MAX_ROUNDS 轮，每轮并行 $PAR）====="
if (( DRY == 1 )); then
  log "DRY RUN：跳过等待，只打印第 1 轮命令"
else
  wait_for_idle
fi

typeset -a plan_lines
round=1
remaining=0
while (( round <= MAX_ROUNDS )); do
  plan_file="$OUT/reseed_plan_r${round}.txt"
  make_plan "$plan_file"
  n=$?
  if (( n == 255 )); then
    log "第 $round 轮无法出清单，终止"
    exit 2
  fi
  if (( n == 0 )); then
    log "第 $round 轮开跑前已无违反，无需补跑"
    remaining=0
    break
  fi
  log "第 $round 轮：$n 个联盟要重播种，清单见 $plan_file"

  rdir="$OUT/reseed_r${round}"
  plan_lines=("${(@f)$(grep '^RESEED ' "$plan_file")}")
  i=0
  for line in $plan_lines; do
    [[ -n "$line" ]] || continue
    read -r kw tag members seeds <<< "$line"
    if (( DRY == 1 )); then
      print -r -- "$PY solver/scripts/run_coalition_experiment.py --instance-id $INST --package $PKG --coalition $members --output-dir $rdir --seed-from-dirs $seeds"
      continue
    fi
    run_one "$tag" "$members" "$seeds" "$rdir" &
    (( i += 1 ))
    (( i % PAR == 0 )) && wait
  done
  wait

  if (( DRY == 1 )); then
    log "DRY RUN：命令已打印，不再往下走"
    exit 0
  fi

  # 跑完立刻重算一遍，看这一轮到底补上没有
  check_file="$OUT/reseed_check_r${round}.txt"
  make_plan "$check_file"
  remaining=$?
  if (( remaining == 255 )); then
    log "第 $round 轮跑完后算不出分摊，终止"
    exit 2
  fi
  log "第 $round 轮跑完：还剩 $remaining 个联盟违反（明细见 $check_file）"
  if (( remaining == 0 )); then
    break
  fi
  (( round += 1 ))
done

if (( remaining > 0 )); then
  log "!! 两轮补跑之后仍有 $remaining 个联盟比拆开还贵：重播种没起作用，"
  log "!! 下面这张分摊表里的这几格不能直接用，须人工看过再说"
  grep '^RESEED ' "$OUT/reseed_check_r${MAX_ROUNDS}.txt" 2>/dev/null | tee -a "$LOG"
fi

build_extra
log "===== 汇总（成本取所有轮次里最小的可行解）====="
"$PY" "$ALLOC" --root "$OUT" "${EXTRA[@]}" --out "$FINAL_JSON" 2>&1 | tee -a "$LOG"
log "===== 联盟成本补跑结束，JSON 落在 $FINAL_JSON ====="
