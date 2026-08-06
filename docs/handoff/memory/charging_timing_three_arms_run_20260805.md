# T23—T25 充电时刻三条线探索批记录（2026-08-05—06）

## 终态

`HALT_T23_RUNNER_STOP_AND_FAILURE_CONTRACT_UNAVAILABLE_NO_SEARCH`。权威证据包为 `docs/handoff/charging_timing_three_arms_run_20260805/`。

## FACT

T23 登记 3 算例 × 3 策略 × 10 种子 = 90 单元，实际搜索 0/90，`paper_claim_allowed=false`。当前 T21 runner 在 full 模式把 600/600/800 参考迭代映射直接传给 HGS；HGS 用 `MaxIterations` 硬停止，并把达到边界记为 `MAX_ITERATIONS`。这不能执行“到参考边界仍改善必须继续”的 T23 合同。

runner 在 `as_completed()` 中直接执行 `future.result()`，任一单元异常会中断整批；CSV、witness 和正式 metadata 又在全部 future 返回后统一物化，不能实现“失败单元原样留证并继续其余单元”。

本轮未运行 runner、solver 或监控器，未改任何代码、策略、审计器、受保护文件或论文目录。原始 CSV 只有表头，witness 为 0。三个受保护文件开收工 SHA-256 一致。

## INFERENCE

直接启动现有 full 模式会跑出错误的停止合同，并在单元失败时可能丢失已完成项的持久化状态；0/90 不构成任何实验读数。

## DECISION

按 T23 铁律停止，不自定“长期平缓”窗口，不将缺失读数写成通过，`paper_claim_allowed=false`。

## HALT_*

`HALT_T23_RUNNER_STOP_AND_FAILURE_CONTRACT_UNAVAILABLE_NO_SEARCH`

## T25 终态

`T25_EXPLORATORY_90_UNITS_MATERIALIZED`。权威证据包仍为
`docs/handoff/charging_timing_three_arms_run_20260805/`；探索批
`paper_claim_allowed=false`。

## T25 FACT

接受批 90/90 个单元、90 个唯一 `(instance_id, arm, seed)` 三元组，成功 90、失败 0；
前一轮 17 行逐字段不变。改善轨迹 3966 行、槽记录 8640 行、MIP 审计 90 行、witness 90 份。
服务不足 0，违反非零 0，搜索目标与最终评价最大绝对闭合误差 0。

T24 的 4589—7622 是三个视角内部最后改善号的最大值，不是串联 20000 次迭代的全局号；
此前据此写“尾部一万两千余次零改善”属于口径混淆。全批 `max局部` 实际范围 3662—7774，
81/90 位于 4589—7622；区间外是 JJJ seed 08 三臂（3662）、PRD seed 08 三臂（4320）和
PRD seed 07 三臂（7774）。串联全局最后改善范围 13387—19774；第 20000 次仍改善为 0，
任一视角自身额度末次迭代恰好改善也为 0。

排除每视角初始化哨兵后，将改善事件按顺序等分早/中/晚三段：晚段幅度中位数低于早段的单元数为
`cv_only 90/90`、`naive_ev 84/90`、`mechanism_ev 87/90`；早≥中≥晚分别只有
48/90、60/90、60/90。未登记“长期平缓”阈值，未据此作收敛判断。

10 种子汇总实际充电碳强度（ASAP / COST / COST_CARBON，kgCO2e/kWh）：
CY `0.208603371 / 0.211494172 / 0.185748338`；JJJ
`0.617120078 / 0.612945743 / 0.575623357`；PRD
`0.325174404 / 0.312025328 / 0.268075986`。全部 30 个算例—种子配对三臂路线签名均相同。
逐槽与逐单元原值见 `slot_distribution.csv` 和 `report.md`。

路线池 MIP 实耗范围 10.006459958—10.496839125 秒，中位数 10.032773625 秒，扩展次数均为 0；
状态分类为 `REJECTED_COMPLETE_MODEL_VIOLATIONS 76`、`NO_INCUMBENT 9`、
`LIMIT_WITH_INCUMBENT 5`。这些是路线池 MIP 审计原值；接受批最终解违反数逐单元为 0。

启动阶段有一次技术编排失败：macOS `spawn` 重执行内联主程序，使剩余 73 个规格均在
`SEARCH_STARTING` 收到 `BrokenProcessPool`，新增成功单元为 0。该无效批隔离于
`docs/handoff/charging_timing_three_arms_run_20260805_T25_launcher_failure_archive/`；主产物恢复到原 17 单元
并复核哈希后，使用 6 个独立单元进程完成续跑。两次内存压力暂停发生在 56/90 和 84/90，
恢复后保持原预算、原并发和科学设置。

## T25 DECISION

`paper_claim_allowed=false`；不按方向筛选、不挑种子、不补跑既有三元组，不记录结果正确性判断。
三个受保护文件开工/收工 SHA-256 一致，runner、算法、策略实现和审计器未修改。

## T25 HALT_*

无材料化 HALT；90 个接受单元均已落盘。技术启动失败另行隔离，不进入接受批结果。
