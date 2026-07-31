# E5 v3 上限预算修正与收敛探针歧义 HALT（2026-07-30）

## 终态

权威目录：
`baselines/china_e3_e7/e5_nonlinear_v3_20260730/`。

根级完成信号：
`done.json.status=HALT_PROBE_AMBIGUOUS_NULL_OBJECTIVE_TRACE`。

本轮没有选出正式预算，没有启动 50c 或 100c 正式实验，完成算例为空，四个科学
端点回答数为 0。`budget_cap=1500` 只表示失败探针的上限，不是正式预算锁。

## 用户批准与已完成的预算语义修正

用户明确批准废止“完整评价数必须精确等于预算”的自建配额判据，改为期刊对齐的上限
语义：`consumed <= cap` 正常，`consumed > cap` 才是预算控制故障。候选耗尽或不再
改进允许提前终止，但必须记录实际消费、上限和明确终止原因。

新入口：

- `baselines/china_e3_e7/run_e5_nonlinear_v3_20260730.py`
- `baselines/china_e3_e7/check_e5_nonlinear_v3_20260730.py`

v3 复用 v2 的 pilot/正式结构、逐单元日志、共同种子与初始解、原子落盘，并在 runner
侧增加 `complete_candidate_evaluations_consumed`、
`complete_candidate_budget_cap` 和 `termination_reason`。没有修改
`route_pool_sp.py` 或 `epochal_hgs.py` 的搜索语义；受保护的 `cost.py`、
`check.py`、`search/evaluation.py` 哈希也未漂移。

## 探针停止现场

收敛探针按 1 worker、两臂共同 cap=1500 启动，先运行
`cn-prd-50c-01-V2-LOCATIONS / seed=1 / L100_control`。监控器约 120.486 秒后记录
`ANOMALY`，进程已退出，原始异常为：

```text
HALT_E5_V3_INVALID_COMPLETE_TRACE:
cn-prd-50c-01-V2-LOCATIONS__seed-01__L100_control
```

v3 runner 在检查 trace 时要求每行 `complete_objective` 非空，并在该检查之后才准备
原子写入单元 trace。因此现场没有持久化本次实际消费次数、改善曲线或 failure strings。
上一轮 v2 的 331 次是历史起点，不能冒充本轮 v3 的已持久化计数；本轮
`median_evaluations_consumed=null`，并明确标记
`NA_NO_PERSISTED_COMPLETE_UNIT`。

## 为什么不能自行判成可继续

只读代码核查确认，`epochal_hgs.py` 会在候选翻译或完整化捕获
`IndexError/KeyError/TypeError/ValueError` 时写入
`complete_objective=null, status=INFEASIBLE_OR_ERROR`，且把该行计入完整候选评价
尝试数。因此“任一 null objective 即 trace 无效”的 runner 判据与上游 schema 不一致。

但 `INFEASIBLE_OR_ERROR` 同时混合两类情况：合法不可行候选，以及翻译/数据/完整化
技术错误。由于 trace 和 failure strings 没有在异常前落盘，当前证据无法区分：

1. 若是合法不可行候选，这是 runner 判据误报。未来经用户批准的新版本应保留该行的
   消费计数，只在 incumbent 曲线更新时跳过空目标，并持久化失败分类后重跑。
2. 若是翻译或数据错误，这是真技术故障，必须先独立诊断并获授权，不能继续正式实验。

用户本轮明确要求“拿不准属于哪一类就停，写明两种后果，不要猜”。因此冻结 v3
runner、不修复、不重试、不启动正式实验是本轮唯一合规终态。

## 证据与恢复边界

四件套、`report.md` 和最后写入的根级 `done.json` 已齐全。清单中的 11 个交付/入口
文件、`source_lock.json` 中 18 个源码哈希全部独立复核一致；AppleDouble 已精确
清除，旧 `e5_nonlinear_20260729/` 与 `e5_nonlinear_v2_20260730/` 保留。

恢复前必须由用户决定是批准“先持久化并细分 null trace 的新 runner 诊断版”，还是先
按真正技术故障调查上游 failure。没有这项决定，不得从 v3 现场直接重试或开启正式
50c/100c。
