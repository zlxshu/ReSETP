# E5-NONLINEAR-CHARGING-V2 收敛探针技术 HALT（2026-07-30）

## 终态

用户以 `experiment_contract_v2_journal_aligned_20260730.md` 整体取代旧
`CONTRACT-E5E7-BLIND-01`，明确废止 L/S 饥饿判据、20% 臂门限和 pilot 阶梯，
并授权直接运行 E5。新入口
`baselines/china_e3_e7/run_e5_nonlinear_v2_20260730.py` 与独立复算器
`check_e5_nonlinear_v2_20260730.py` 已建立；旧 runner 和
`e5_nonlinear_20260729/` 封存包未改。

1500 次完整候选评价的两臂收敛探针在 L100_control 首个返回单元触发
`HALT_E5_V2_NONEXACT_BUDGET:...:331:1500:1500`。按用户“真正技术故障即停，
不得自行修复后继续”的硬约束，判决
`HALT_PROBE_NONEXACT_BUDGET`；未重试、未改预算/种子/算例/判据，50c 与 100c
正式实验均未启动，四个科学端点均为
`NOT_RUN_UPSTREAM_TECHNICAL_FAILURE`。

## 可复算原因

`epochal_hgs.py` 的 terminal-population archive 通过
`proxy_ranked[:max_archive_candidates]` 取候选，故配置值只是上限，实际评价数
由真实唯一 native population 决定。`route_pool_sp.py` 的
`complete_candidate_budget_expected` 却按三个配置上限加固定评价计算。1500 长档
下实际 trace 只有 331 次，和 expected=1500 不等，runner 按精确预算合同 fail
closed。该故障说明“archive 上限→精确完整候选预算”的接口在长档不成立，不是
目标值方向、资源压力或旧 L/S 门禁。

## 证据与保护边界

权威目录：
`baselines/china_e3_e7/e5_nonlinear_v2_20260730/`。`raw_runs.csv` 只登记
traceback 明确给出的 L100 探针失败行，不补造另一并发臂结果；`decision.json`
把四端点标为 NOT_RUN。监控现场在
`monitor_runtime/probe/scenes/20260730-030051-anomaly/`，自动 AI 关闭。

关闭复核中 `cost.py`、`check.py`、`search/evaluation.py`、`route_pool_sp.py`
哈希分别保持
`2717b4...80be`、`9c81e2...03a8`、`c72152...6fc3`、
`976ef2...2c1`；旧 E5 201 文件整树摘要与跑前一致。继续前必须由用户另行授权
技术处理方案，解决固定完整候选预算的精确消费；本轮不代替用户选择修复路径。
