# E5 非线性充电机制 v2：收敛探针技术 HALT

## 结论

本轮终态为 `HALT_PROBE_NONEXACT_BUDGET`，不是 E5 科学结果。按用户的“出现真正技术故障即停、不得自行修复后继续”约束，正式 50c/100c 实验均未启动，四个科学端点全部为 `NOT_RUN_UPSTREAM_TECHNICAL_FAILURE`。

新的 v2 入口和独立复算器已经建立。v2 runner 不含 `STARVATION_FRACTION_THRESHOLD`、`STARVED_UNIT_SHARE_LIMIT`、pilot 阶梯或任何以 `L/S` 决定准入/通过的代码；完整候选评价预算是无默认值的命令行必填参数，并实现了逐 `instance-seed-arm` 的无缓冲进度行。旧 runner 和 `e5_nonlinear_20260729/` 封存目录没有改写。

## 故障事实

收敛探针按合同在 `cn-prd-50c-01-V2-LOCATIONS`、seed=1 上以 2 workers 启动，两臂请求预算均为 1500 次完整候选评价。环境预检通过：Python 3.13.9、PyVRP 0.12.2、四个数值线程变量均固定为 1；监控器自动 AI 关闭。

L100_control 单元返回 `complete_candidate_evaluation_attempts=331`，而 runner/路线池按配置计算的 `complete_candidate_budget_expected=1500`。因此触发：

```text
HALT_E5_V2_NONEXACT_BUDGET:
cn-prd-50c-01-V2-LOCATIONS__seed-01__L100_control:331:1500:1500
```

代码级原因可以复算：`epochal_hgs.py` 的 terminal-population archive 使用 `[:max_archive_candidates]`，该数值是上限；实际完整评价次数由真实 `proxy_ranked` 长度决定。`route_pool_sp.py` 的 expected budget 则使用三个配置上限之和再加固定评价。在长预算下，真实唯一 native 候选少于配置上限，故“请求预算=精确消费预算”的映射失效。这里报告的是接口/计数技术故障，不是目标值不好看，也不是旧饥饿判据复发。

## 科学端点状态

| 端点 | 状态 |
|---|---|
| NL90 完整可行率 | `NOT_RUN_UPSTREAM_TECHNICAL_FAILURE` |
| L100 假可行数与成因 | `NOT_RUN_UPSTREAM_TECHNICAL_FAILURE` |
| 共同可行配对的成本效应 | `NOT_RUN_UPSTREAM_TECHNICAL_FAILURE` |
| 逐会话起止 SOC 与时长差 | `NOT_RUN_UPSTREAM_TECHNICAL_FAILURE` |

没有形成合法的收敛曲线、平台评价数或正式共用预算；没有正式方案、独立科学证书、臂间成本比较或会话效应。`raw_runs.csv` 只登记已明确抛出的 L100 探针失败行，不把另一并发臂的未返回状态补写成结果。

## 完整性

故障后没有修复 runner、改预算、换种子、换算例或继续正式搜索。关闭复核中，`cost.py`、`check.py`、`search/evaluation.py`、`route_pool_sp.py` 与跑前哈希完全相同；旧 `e5_nonlinear_20260729/` 的 201 个文件整树摘要也与跑前一致。监控现场保存在 `monitor_runtime/probe/scenes/20260730-030051-anomaly/`，其 stdout traceback 在 `monitor_runtime/probe/experiment.stdout.log`；监控目录和 AppleDouble `._*` 均排除在科学哈希清单之外。

若要继续，必须先由用户明确授权一个新的技术处理任务，解决“固定完整候选评价预算如何保证精确消费”的 runner/调度接口；本轮没有代替用户选择修复方案。
