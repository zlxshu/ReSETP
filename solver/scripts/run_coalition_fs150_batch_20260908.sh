#!/bin/zsh
# 2026-09-08：4.6 后半（四家企业分摊方法对比）在最终算例包上的探针批。
# 只跑 6 个联盟：四家单干（D1..D4）+ 东莞佛山广州三家集群 + 四家全联合。
# 目录名由脚本自己按 D1..Dn 命名，--output-dir 传根目录即可。
set -u
REPO="/Volumes/移动硬盘（512G）/ReSETP"
cd "$REPO"
PY="$REPO/.public-hgs-venv/bin/python3"
export PYTHONPATH='solver/src:third_party/setp_hgs_kernel:models/src'
OUT="solver/reports/coalition_fs150_v6_20260908"
PKG="data/ChinaInstances/china81_final_suite_v2_20260815"
INST="cn-prd-150c-01-V3-TWO-SHIFT-FS"
mkdir -p "$OUT"

run_one() {  # $1=日志名 $2=联盟成员 $3...=额外参数
  local tag="$1"; shift
  local members="$1"; shift
  print "[$(date +%H:%M:%S)] 启动 $tag"
  "$PY" solver/scripts/run_coalition_experiment.py \
      --instance-id "$INST" --package "$PKG" \
      --coalition "$members" --output-dir "$OUT" "$@" \
      >> "$OUT/$tag.log" 2>&1
  print "[$(date +%H:%M:%S)] 完成 $tag exit=$?"
}

# 第一阶段：四家单干，4 个并行（打满 4 个性能核）。
run_one D1 D_dongguan  &
run_one D2 D_foshan    &
run_one D3 D_guangzhou &
run_one D4 D_shenzhen  &
wait

# 第二阶段：两个多成员联盟并行，用单干最优解做种子（脚本按 D1..Dn 自己找）。
run_one CLUSTER "D_dongguan,D_foshan,D_guangzhou" --seed-singletons-root "$OUT" &
run_one GRAND "D_dongguan,D_foshan,D_guangzhou,D_shenzhen" --seed-singletons-root "$OUT" &
wait
print "[$(date +%H:%M:%S)] 联盟探针批结束"
