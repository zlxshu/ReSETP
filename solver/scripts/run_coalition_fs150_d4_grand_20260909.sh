#!/bin/zsh
# 2026-09-09：深圳单干从空闲参考起手失败（内核首轮 26 个候选精确评价全不可行）。
# 探针已证明旧批 PRDFIX 深圳解在这份逐项相同的 FS 算例 + 当前模型下可行（5096.59 元），
# 故用它做起手参考重跑 D4，再用四家单干做种子跑 GRAND。
set -u
REPO="/Volumes/移动硬盘（512G）/ReSETP"; cd "$REPO"
PY="$REPO/.public-hgs-venv/bin/python3"
export PYTHONPATH='solver/src:third_party/setp_hgs_kernel:models/src'
OUT="solver/reports/coalition_fs150_v6_20260908"
PKG="data/ChinaInstances/china81_final_suite_v2_20260815"
INST="cn-prd-150c-01-V3-TWO-SHIFT-FS"
run_one() { local tag="$1"; shift; local members="$1"; shift
  print "[$(date +%H:%M:%S)] 启动 $tag"
  "$PY" solver/scripts/run_coalition_experiment.py --instance-id "$INST" --package "$PKG" \
      --coalition "$members" --output-dir "$OUT" "$@" >> "$OUT/$tag.log" 2>&1
  print "[$(date +%H:%M:%S)] 完成 $tag exit=$?"; }
run_one D4 D_shenzhen --seed-from-dirs solver/reports/coalition_prd150_20260830/D4/run_1
run_one GRAND "D_dongguan,D_foshan,D_guangzhou,D_shenzhen" --seed-singletons-root "$OUT"
print "[$(date +%H:%M:%S)] 批结束"
