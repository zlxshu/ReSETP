#!/bin/zsh
# 2026-09-05 运行协议：M1 4 性能核，交付批 ≤3 并行、不降优先级（speed_diagnosis_20260905.md §3e）
# 企业作业时间窗杠杆（表11 新增行）的单个任务：
#   run_lever_workwindow_one.sh <OUT_ROOT> "<tag>|<run>"
#   tag = lunch1114     ：正式档，算例 ...-LUNCH1114（午休 11:00–14:00，
#                          下午班 14:00–20:00，PM 客户窗整体 +60 分钟）
#         probe_identity：复制通道恒等探针，算例同样是 ...-LUNCH1114，
#                          但要在**尚未改动副本**时跑，用来证明"只复制不改"
#                          走的是同一条 _build_saved_suite_context 通道
#   run = 两位数序号（01/02/03）
# 除算例 id 外，一切与基准（ablation_formal_10x_v5_20260904 的 MTC-HGS 臂）一致：
#   不传 --tariff-calendar-authority（北京现行电价日历），碳价 0.2，臂 MTC-HGS，
#   COMMON 参数与 run_private_axes_one.sh 逐条相同。
# 目录结构 <OUT_ROOT>/lunch1114/MTC-HGS/run_<kk>，探针写 <OUT_ROOT>/probe_identity。
# 幂等：已有 best_solution.json 的跳过。
set -u
OUT_ROOT="$1"; job="$2"
tag="${job%%|*}"; run="${job##*|}"
REPO="$(cd "$(dirname "$0")/../.." && pwd -P)"
cd "$REPO"
PY="$REPO/.public-hgs-venv/bin/python3"
export PYTHONPATH='solver/src:third_party/setp_hgs_kernel:models/src'
INSTANCE=cn-jjj-50c-01-DEPOTSEARCH-d996f755bd-LUNCH1114
case "$tag" in
  lunch1114)      dir="$OUT_ROOT/lunch1114/MTC-HGS/run_$run"; log_dir="$OUT_ROOT/lunch1114/MTC-HGS"; log="$log_dir/run_$run.log" ;;
  probe_identity) dir="$OUT_ROOT/probe_identity";             log_dir="$OUT_ROOT";                  log="$OUT_ROOT/probe_identity.log" ;;
  *) print "未知档 $tag"; exit 3 ;;
esac
if [[ -f "$dir/best_solution.json" ]]; then print "跳过 $tag/run_$run（已完成）"; exit 0; fi
mkdir -p "$log_dir"
COMMON=(
  --instance-id "$INSTANCE"
  --fleet-parameter-class endogenous
  --population-mode copied_hgs_defaults
  --recharge-mode on_demand
  --depot-curve registered
  --charge-timing-policy cost_plus_carbon
  --charging-prescreen
  --search-mode kernel_native
  --no-ev-charge-time-proxy
  --ev-reload-gap-proxy
  --confirming-round
)
print "[$(date +%H:%M:%S)] 启动 $tag/run_$run"
"$PY" solver/scripts/run_problem_hgs_private_technical.py \
    "$dir" --data-repo-root . --arm "MTC-HGS" "${COMMON[@]}" \
    --carbon-price 0.2 \
    >> "$log" 2>&1
rc=$?
print "[$(date +%H:%M:%S)] 完成 $tag/run_$run exit=$rc"
