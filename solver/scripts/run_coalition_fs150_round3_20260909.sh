#!/bin/zsh
# 2026-09-09 第三轮：深圳改进后，拆分方向再次不一致——
#   D1+D3+D4 7787.07 > D1+D3(3650.37)+D4(4085.23)=7735.60；GRAND 8915.21 > D1+D2+D3(4484.42)+D4(4085.23)=8569.65。
# 两格按最优拆分重新播种；跑完自动做两方向核对（拆分：分摊脚本结构检查；投影：探针）。
set -u
REPO="/Volumes/移动硬盘（512G）/ReSETP"; cd "$REPO"
PY="$REPO/.public-hgs-venv/bin/python3"
export PYTHONPATH='solver/src:third_party/setp_hgs_kernel:models/src:solver/scripts'
OUT="solver/reports/coalition_fs150_v6_20260908"
PKG="data/ChinaInstances/china81_final_suite_v2_20260815"
INST="cn-prd-150c-01-V3-TWO-SHIFT-FS"
run_one() { local tag="$1"; local members="$2"; local seeds="$3"
  print "[$(date +%H:%M:%S)] 启动 $tag（种子 $seeds）"
  "$PY" solver/scripts/run_coalition_experiment.py --instance-id "$INST" --package "$PKG" \
      --coalition "$members" --output-dir "$OUT" --seed-from-dirs "$seeds" >> "$OUT/${tag}_r3.log" 2>&1
  print "[$(date +%H:%M:%S)] 完成 $tag exit=$?"; }
run_one T134 "D_dongguan,D_guangzhou,D_shenzhen" "$OUT/D1+D3/run_1,$OUT/D4/run_1" &
run_one GRAND "D_dongguan,D_foshan,D_guangzhou,D_shenzhen" "$OUT/D1+D2+D3/run_1,$OUT/D4/run_1" &
wait
print "[$(date +%H:%M:%S)] 第三轮求解结束，两方向核对"
"$PY" solver/scripts/coalition_allocation_four_firm.py --root "$OUT" --out "$OUT/allocation_four_firm_round3.json" > "$OUT/allocation_round3.txt" 2>&1
"$PY" solver/reports/coalition_fs150_v6_20260908/probe_projection_consistency.py 2>&1 | grep -v "PenaltyBound\|warn(" > "$OUT/projection_check_round3.txt"
print "[$(date +%H:%M:%S)] 第三轮全部结束；投影欠搜：$(grep -c '^欠搜 ' $OUT/projection_check_round3.txt)；拆分违规：$(grep -c 'superadditiv' $OUT/allocation_round3.txt)"
