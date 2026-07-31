# E5 非线性充电 v3：收敛探针 HALT 报告

## 结论

本轮状态为 `HALT_PROBE_AMBIGUOUS_NULL_OBJECTIVE_TRACE`。预算语义已经在 runner 侧改为“上限而非配额”：实际完整候选评价次数小于等于上限属于正常，只有超过上限才触发预算控制故障；`route_pool_sp.py`、`epochal_hgs.py` 以及三个受保护求解/核查文件均未修改且哈希闭合。

1500 上限收敛探针在首个单元 `cn-prd-50c-01-V2-LOCATIONS / seed=1 / L100_control` 完成搜索返回后，触发 `HALT_E5_V3_INVALID_COMPLETE_TRACE`。runner 在原子写入该单元的 trace 与状态之前抛出异常，因此当前 v3 现场没有可恢复的实际评价次数、改善曲线或失败候选明细。正式共同预算未选出，50c 与 100c 正式实验均未启动，四个科学端点回答数为 0。没有把上一轮 v2 的 331 次冒充为本轮 v3 的已持久化计数。

## 预算语义修正

v3 runner 保留了 v2 的探针阶梯、并行框架、逐单元日志和原子落盘结构，只替换 runner 侧预算判据与账本字段。正常科学终止预定为 `BUDGET_CAP_REACHED`、`CANDIDATES_EXHAUSTED` 或 `NO_IMPROVEMENT`；`complete_candidate_evaluations_consumed > complete_candidate_budget_cap` 才是 `HALT_E5_V3_BUDGET_CAP_EXCEEDED`。本次停机不是“没有跑满 1500”触发的旧配额误报。

`raw_runs.csv` 同时保留 `complete_candidate_evaluations_consumed` 与 `complete_candidate_budget_cap`。首个单元的 cap 是 1500；consumed 因异常前未持久化而留空，并由 `complete_candidate_evaluations_consumed_status=NOT_PERSISTED_BEFORE_EXCEPTION` 明确区分于数值 0。

## 新停机的硬证据

监控器运行 120.486 秒后记录 `ANOMALY`，进程已退出；发现项为 `FATAL_LOG_PATTERN` 与 `PROCESS_EXITED_WITHOUT_COMPLETION`。异常现场为 `baselines/china_e3_e7/e5_nonlinear_v3_20260730/monitor_runtime/probe/scenes/20260730-032408-anomaly`，原始 traceback 在 `probe_run.log`。异常时系统 `memory_pressure` 可用比例为 41%，本轮按预检决定使用 1 个 worker。

静态只读核查表明，`epochal_hgs.py` 会在候选翻译或完整化抛出 `IndexError/KeyError/TypeError/ValueError` 时写入 `complete_objective=null, status=INFEASIBLE_OR_ERROR`，并把该行计入 `complete_candidate_evaluation_attempts`。v3 runner 的额外校验却把任何 null objective 一律视为无效 trace。两者的 schema 语义不一致。

但是，`INFEASIBLE_OR_ERROR` 同时覆盖“合法不可行候选”和“翻译/数据技术错误”，而本轮 runner 在持久化 trace 与 failure strings 之前停止。故现有现场无法可靠判断属于哪一类。依照任务规则“拿不准则停止并写明两种处理后果”，本轮没有修改冻结 runner、没有重试、没有启动正式实验。

## 两种解释及后果

若 null 行只是合法不可行候选评价，则这是 runner 判据误报。未来经用户批准的新版本应把该行继续计入实际消费次数，只在绘制 incumbent 改善曲线时跳过空目标值，同时持久化 status 与失败原因，再从新版本重跑探针。

若 null 行来自候选翻译、数据或完整化错误，则属于真正技术故障。必须先独立诊断上游原因并获得授权，不能把它当作正常早停继续，否则会污染正式证据。

当前证据不能在这两种解释之间作选择。

## 收敛探针与正式预算

| 探针臂 | 上限 | 实际消费 | 改善曲线 | 科学终止原因 |
|---|---:|---:|---|---|
| L100_control | 1500 | NA（异常前未持久化） | NOT_WRITTEN | HALT，不是科学终止 |
| NL90_mild | 1500 | NOT_RUN | NOT_RUN | NOT_RUN |

因此不能按“平台点向上取整到整百并留余量”的规则选出正式共同上限。`budget_cap=1500` 在本报告和 `done.json` 中仅指本次探针上限，不代表已经锁定的正式实验上限。

## 正式实验与四个端点

| 算例 | Best | Avg | Gap% | 车辆数 | 时间 | 实际评价数 | 状态 |
|---|---:|---:|---:|---:|---:|---:|---|
| cn-prd-50c-01-V2-LOCATIONS | NA | NA | NA | NA | NA | NA | NOT_RUN_UPSTREAM_PROBE_HALT |
| cn-prd-100c-02-V2-LOCATIONS | NA | NA | NA | NA | NA | NA | NOT_RUN_UPSTREAM_PROBE_HALT |

NL90 完整可行率、L100 可行但 NL90 物理下不可行的数量与成因、双臂均可行单元的完整模型成本变化、逐会话起止 SOC 与充电时长差均未生成。任何正、负或零效应结论在本轮都不受支持。

## 完整性与边界

`cost.py`、`check.py`、`search/evaluation.py`、`route_pool_sp.py` 与 `epochal_hgs.py` 的当前哈希均与 `source_lock.json` 一致。旧目录 `e5_nonlinear_20260729/` 和 `e5_nonlinear_v2_20260730/` 均保留。哈希清单排除了 AppleDouble、`__pycache__`、`.pytest_cache`、监控运行态和最后写入的 `done.json`；本目录内发现的 AppleDouble sidecar 已在清单生成前删除。
