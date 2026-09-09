#!/bin/zsh
# 2026-09-09：GRAND（PID 38334, tmux会话coal2）跑完后，补齐4.6后半剩余9个联盟
# （6个两家组合 + 3个三家组合），再按需重跑GRAND（若GRAND坍缩成D1+D2+D3与D4的并集）。
# 本脚本自己先等当前GRAND跑完，可以现在就用下面这条命令启动，与coal2会话相同的约定：
#   tmux new-session -d -s coal3 caffeinate -i zsh \
#     '/Volumes/移动硬盘（512G）/ReSETP/solver/scripts/run_coalition_fs150_rest_20260909.sh' \
#     >> '/Volumes/移动硬盘（512G）/ReSETP/solver/reports/coalition_fs150_v6_20260908_batch.log' 2>&1
#
# 注意：run_coalition_experiment.py内部按depot数量自动生成tag（_label函数）——
# 四家全联合时无论--coalition怎么写，tag永远算成"GRAND"，且_run_one对已存在的
# output目录会raise FileExistsError拒绝覆盖。因此GRAND_seeded_cluster不能直接写
# 到"$OUT"下（会跟已有GRAND撞名），改用独立子目录"$OUT/GRAND_seeded_cluster"做
# --output-dir，实际产物落在"$OUT/GRAND_seeded_cluster/GRAND/run_1/"。
set -u
REPO="/Volumes/移动硬盘（512G）/ReSETP"
cd "$REPO"
PY="$REPO/.public-hgs-venv/bin/python3"
export PYTHONPATH='solver/src:third_party/setp_hgs_kernel:models/src'
OUT="solver/reports/coalition_fs150_v6_20260908"
PKG="data/ChinaInstances/china81_final_suite_v2_20260815"
INST="cn-prd-150c-01-V3-TWO-SHIFT-FS"
GRAND_SEEDED_DIR="$OUT/GRAND_seeded_cluster"
mkdir -p "$OUT"

run_one() {  # $1=tag(日志名/预期目录名) $2=联盟成员(逗号分隔depot id) $3...=额外参数
  local tag="$1"; shift
  local members="$1"; shift
  print "[$(date +%H:%M:%S)] 启动 $tag"
  "$PY" solver/scripts/run_coalition_experiment.py \
      --instance-id "$INST" --package "$PKG" \
      --coalition "$members" --output-dir "$OUT" "$@" \
      >> "$OUT/$tag.log" 2>&1
  print "[$(date +%H:%M:%S)] 完成 $tag exit=$?"
}

launch() {  # $1=tag $2=联盟成员，已有best_solution.json就跳过，否则后台起跑
  local tag="$1" members="$2"
  if [[ -f "$OUT/$tag/run_1/best_solution.json" ]]; then
    print "[$(date +%H:%M:%S)] 跳过 $tag（已有 best_solution.json）"
    return
  fi
  run_one "$tag" "$members" --seed-singletons-root "$OUT" &
}

read_cost() {  # $1=best_solution.json路径；打印evaluation.total_cost，缺失/出错打印空
  local path="$1"
  if [[ ! -f "$path" ]]; then
    print ""
    return
  fi
  "$PY" - "$path" <<'PYEOF'
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as f:
        d = json.load(f)
    print(d["evaluation"]["total_cost"])
except Exception:
    print("")
PYEOF
}

report_cost() {  # $1=tag $2=best_solution.json路径，打印一行tag与total_cost
  local tag="$1" path="$2" cost
  cost=$(read_cost "$path")
  if [[ -n "$cost" ]]; then
    print "  $tag total_cost=$cost"
  else
    print "  $tag <best_solution.json 不存在或读取失败: $path>"
  fi
}

# ---------- 第一步：等当前 run_coalition_experiment.py（GRAND, PID 38334）跑完 ----------
if pgrep -f "run_coalition_experiment.py" >/dev/null 2>&1; then
  print "[$(date +%H:%M:%S)] 检测到 run_coalition_experiment.py 仍在跑，开始等待（每60秒轮询一次）"
  while pgrep -f "run_coalition_experiment.py" >/dev/null 2>&1; do
    sleep 60
  done
fi
print "[$(date +%H:%M:%S)] 未检测到运行中的 run_coalition_experiment.py，继续执行"

# ---------- 第二步：剩余9个联盟，最多3个并行（M1四性能核），已存在的跳过 ----------
# 两家组合（6个），按 D1<D2<D3<D4 canonical顺序分两批，每批≤3个并行
launch "D1+D2" "D_dongguan,D_foshan"
launch "D1+D3" "D_dongguan,D_guangzhou"
launch "D1+D4" "D_dongguan,D_shenzhen"
wait
launch "D2+D3" "D_foshan,D_guangzhou"
launch "D2+D4" "D_foshan,D_shenzhen"
launch "D3+D4" "D_guangzhou,D_shenzhen"
wait

# 三家组合（3个），一批并行
launch "D1+D2+D4" "D_dongguan,D_foshan,D_shenzhen"
launch "D1+D3+D4" "D_dongguan,D_guangzhou,D_shenzhen"
launch "D2+D3+D4" "D_foshan,D_guangzhou,D_shenzhen"
wait
print "[$(date +%H:%M:%S)] 9个剩余联盟批次结束"

# ---------- 第三步：判定GRAND是否坍缩成D1+D2+D3与D4的并集，坍缩才重跑 ----------
GRAND_JSON="$OUT/GRAND/run_1/best_solution.json"
D123_JSON="$OUT/D1+D2+D3/run_1/best_solution.json"
D4_JSON="$OUT/D4/run_1/best_solution.json"
GRAND_COST=$(read_cost "$GRAND_JSON")
D123_COST=$(read_cost "$D123_JSON")
D4_COST=$(read_cost "$D4_JSON")

if [[ -n "$GRAND_COST" && -n "$D123_COST" && -n "$D4_COST" ]]; then
  SHOULD_RESEED=$("$PY" -c "print('1' if float('$GRAND_COST') > float('$D123_COST') + float('$D4_COST') else '0')")
  if [[ "$SHOULD_RESEED" == "1" ]]; then
    print "[$(date +%H:%M:%S)] GRAND=$GRAND_COST > D1+D2+D3($D123_COST)+D4($D4_COST)，判定为坍缩成并集，重跑 GRAND_seeded_cluster"
    print "[$(date +%H:%M:%S)] 启动 GRAND_seeded_cluster"
    "$PY" solver/scripts/run_coalition_experiment.py \
        --instance-id "$INST" --package "$PKG" \
        --coalition "D_dongguan,D_foshan,D_guangzhou,D_shenzhen" \
        --output-dir "$GRAND_SEEDED_DIR" \
        --seed-from-dirs "$OUT/D1+D2+D3/run_1,$OUT/D4/run_1" \
        >> "$OUT/GRAND_seeded_cluster.log" 2>&1
    print "[$(date +%H:%M:%S)] 完成 GRAND_seeded_cluster exit=$?"
  else
    print "[$(date +%H:%M:%S)] GRAND=$GRAND_COST <= D1+D2+D3($D123_COST)+D4($D4_COST)，未坍缩，不重跑GRAND"
  fi
else
  print "[$(date +%H:%M:%S)] 警告：GRAND / D1+D2+D3 / D4 三者之一缺 best_solution.json（GRAND=$GRAND_COST D123=$D123_COST D4=$D4_COST），跳过坍缩判定"
fi

# ---------- 第四步：把所有联盟tag与total_cost写进批日志 ----------
print "[$(date +%H:%M:%S)] ===== 全部联盟 total_cost 汇总 ====="
report_cost "D1" "$OUT/D1/run_1/best_solution.json"
report_cost "D2" "$OUT/D2/run_1/best_solution.json"
report_cost "D3" "$OUT/D3/run_1/best_solution.json"
report_cost "D4" "$OUT/D4/run_1/best_solution.json"
report_cost "D1+D2" "$OUT/D1+D2/run_1/best_solution.json"
report_cost "D1+D3" "$OUT/D1+D3/run_1/best_solution.json"
report_cost "D1+D4" "$OUT/D1+D4/run_1/best_solution.json"
report_cost "D2+D3" "$OUT/D2+D3/run_1/best_solution.json"
report_cost "D2+D4" "$OUT/D2+D4/run_1/best_solution.json"
report_cost "D3+D4" "$OUT/D3+D4/run_1/best_solution.json"
report_cost "D1+D2+D3" "$OUT/D1+D2+D3/run_1/best_solution.json"
report_cost "D1+D2+D4" "$OUT/D1+D2+D4/run_1/best_solution.json"
report_cost "D1+D3+D4" "$OUT/D1+D3+D4/run_1/best_solution.json"
report_cost "D2+D3+D4" "$OUT/D2+D3+D4/run_1/best_solution.json"
report_cost "GRAND" "$GRAND_JSON"
if [[ -d "$GRAND_SEEDED_DIR" ]]; then
  report_cost "GRAND_seeded_cluster" "$GRAND_SEEDED_DIR/GRAND/run_1/best_solution.json"
fi
print "[$(date +%H:%M:%S)] 批结束"
