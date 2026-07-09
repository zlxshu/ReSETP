# Task Card — E2 hang-account resume: A13 full parity → A14

日期：2026-07-09
模式：M1 诊断 / 非正式 T3

## 已读强制入口
HANDOFF / READ_ME_FIRST / PRD v2 / planning / memory / MASTER / CLAUDE

## 目标
恢复挂帐的 E2 性能主线：在独立 ALNS + 正式算例底座上，先闭合 A13 完整 parity，再决定 A14 hybrid。

## 输入
- `baselines/e2_alns/lns_policy_kernel_probe_20260708/`（已有 4000/8000 全量、16000 部分 checkpoint）
- hard subset: `route_compression_probe_20260705/hard_subset_instances.csv`（16 例）
- 底座：`algorithms/resetp_alns` + L-main 9 阶三班倒（正式对比用；A13 仍用 hard-subset e2 路径做 policy parity）

## 允许改
- 诊断 runner / 报告 / 新 A14 诊断 flag（默认关闭）
- HANDOFF / memory / 四件套

## 禁止改
- cost.py / check.py / evaluation.py 语义
- prices 默认 / TeX
- 包装未过门结果为胜利

## 命令（续跑）
```bash
PYTHONPATH=solver/src:models/src:. PYTHONHASHSEED=0 \
/opt/anaconda3/bin/python3.13 baselines/e2_alns/lns_policy_kernel_probe.py \
  --output-dir baselines/e2_alns/lns_policy_kernel_probe_20260708 \
  --budgets 4000,8000,16000 --seeds 1,2,3 --workers 3
```

## 验收
- `decision.json` verdict=`A13_PARITY_SUPPORTED` 且 `full_gate=true`、rows=576/576
- 若 fail → 只写 `parity_failure_report.md`，不进 A14
- 若 pass → 允许 A14_ADAPTIVE_LNS_KERNEL_ALNS 诊断探针

## 停止条件
- under-eval / 违约 / protected 语义改动
- A13 未过门仍写 hybrid 胜利

## 产物
四件套 + report + HANDOFF 条目
