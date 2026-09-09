#!/bin/zsh
# 2026-09-09 第二轮：投影核对发现深圳单干欠搜 578.77（三家联盟解里的深圳部分只花 4085.23）。
# 深圳用该投影做种子重跑；随后所有含深圳的联盟按"最优分割"重新播种（分割里用新的深圳解）；最后自动再跑一遍投影核对。
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
      --coalition "$members" --output-dir "$OUT" --seed-from-dirs "$seeds" >> "$OUT/${tag}_r2.log" 2>&1
  print "[$(date +%H:%M:%S)] 完成 $tag exit=$?"; }
# 阶段 1：深圳单干（投影种子）
run_one D4 D_shenzhen "$OUT/seeds/D4_proj_from_D1D3D4/run_1"
# 阶段 2：三对（新深圳 + 对方单干），4 并行上限
run_one P14 "D_dongguan,D_shenzhen"  "$OUT/D1/run_1,$OUT/D4/run_1" &
run_one P24 "D_foshan,D_shenzhen"    "$OUT/D2/run_1,$OUT/D4/run_1" &
run_one P34 "D_guangzhou,D_shenzhen" "$OUT/D3/run_1,$OUT/D4/run_1" &
wait
# 阶段 3：两个三家 + 全联合（各自最优分割：pair + 单干；全联合用 D1+D3+D4 + D2，它已含改进后的深圳）
run_one T124 "D_dongguan,D_foshan,D_shenzhen"  "$OUT/D1+D2/run_1,$OUT/D4/run_1" &
run_one T234 "D_foshan,D_guangzhou,D_shenzhen" "$OUT/D2+D3/run_1,$OUT/D4/run_1" &
run_one GRAND "D_dongguan,D_foshan,D_guangzhou,D_shenzhen" "$OUT/D1+D3+D4/run_1,$OUT/D2/run_1" &
wait
print "[$(date +%H:%M:%S)] 第二轮求解结束，开始投影核对"
"$PY" solver/reports/coalition_fs150_v6_20260908/probe_projection_consistency.py 2>&1 | grep -v "PenaltyBound\|warn(" > "$OUT/projection_check_round2.txt"
print "[$(date +%H:%M:%S)] 第二轮全部结束；欠搜格子：$(grep -c '^欠搜' $OUT/projection_check_round2.txt)"
