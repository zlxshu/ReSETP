#!/bin/zsh
# 2026-09-09：超可加性修复。三个联盟从单干种子起手没追上各自最优分割（联盟比拆开贵），
# 改用最优分割的解做种子重跑：种子成本＝分割成本，搜索只会更低。与旧批"pairs_seeded"同法，只是种子换成更优的分割。
set -u
REPO="/Volumes/移动硬盘（512G）/ReSETP"; cd "$REPO"
PY="$REPO/.public-hgs-venv/bin/python3"
export PYTHONPATH='solver/src:third_party/setp_hgs_kernel:models/src'
OUT="solver/reports/coalition_fs150_v6_20260908"
PKG="data/ChinaInstances/china81_final_suite_v2_20260815"
INST="cn-prd-150c-01-V3-TWO-SHIFT-FS"
run_one() { local tag="$1"; local members="$2"; local seeds="$3"
  print "[$(date +%H:%M:%S)] 启动 $tag（种子 $seeds）"
  "$PY" solver/scripts/run_coalition_experiment.py --instance-id "$INST" --package "$PKG" \
      --coalition "$members" --output-dir "$OUT" --seed-from-dirs "$seeds" >> "$OUT/$tag.log" 2>&1
  print "[$(date +%H:%M:%S)] 完成 $tag exit=$?"; }
run_one T124 "D_dongguan,D_foshan,D_shenzhen"            "$OUT/D1+D2/run_1,$OUT/D4/run_1" &
run_one T234 "D_foshan,D_guangzhou,D_shenzhen"           "$OUT/D2+D3/run_1,$OUT/D4/run_1" &
run_one GRAND "D_dongguan,D_foshan,D_guangzhou,D_shenzhen" "$OUT/D1+D3+D4/run_1,$OUT/D2/run_1" &
wait
print "[$(date +%H:%M:%S)] 超可加性修复批结束"
