#!/bin/zsh
# 2026-09-09：补齐四家企业算例剩余 9 个联盟（6 个两两 + 3 个三家），全部用单干最优解做种子（与旧批 pairs_seeded 同法）。
# 4 个并行打满性能核；两两联盟先跑（小），三家后跑。
set -u
REPO="/Volumes/移动硬盘（512G）/ReSETP"; cd "$REPO"
PY="$REPO/.public-hgs-venv/bin/python3"
export PYTHONPATH='solver/src:third_party/setp_hgs_kernel:models/src'
OUT="solver/reports/coalition_fs150_v6_20260908"
PKG="data/ChinaInstances/china81_final_suite_v2_20260815"
INST="cn-prd-150c-01-V3-TWO-SHIFT-FS"
run_one() { local tag="$1"; local members="$2"
  print "[$(date +%H:%M:%S)] 启动 $tag"
  "$PY" solver/scripts/run_coalition_experiment.py --instance-id "$INST" --package "$PKG" \
      --coalition "$members" --output-dir "$OUT" --seed-singletons-root "$OUT" >> "$OUT/$tag.log" 2>&1
  print "[$(date +%H:%M:%S)] 完成 $tag exit=$?"; }
run_one P12 "D_dongguan,D_foshan" & run_one P13 "D_dongguan,D_guangzhou" &
run_one P14 "D_dongguan,D_shenzhen" & run_one P23 "D_foshan,D_guangzhou" & wait
run_one P24 "D_foshan,D_shenzhen" & run_one P34 "D_guangzhou,D_shenzhen" &
run_one T124 "D_dongguan,D_foshan,D_shenzhen" & run_one T134 "D_dongguan,D_guangzhou,D_shenzhen" & wait
run_one T234 "D_foshan,D_guangzhou,D_shenzhen"
print "[$(date +%H:%M:%S)] 剩余 9 个联盟批结束"
