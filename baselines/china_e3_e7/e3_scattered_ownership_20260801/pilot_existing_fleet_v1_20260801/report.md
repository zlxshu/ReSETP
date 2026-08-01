# E3 existing-fleet pilot v1

**结论：HALT_ORIGINAL_FLEET_STANDALONE_CAPACITY_INFEASIBLE。**

运行时源码快照：`../source_snapshot/run_e3_scattered_ownership.py`，SHA-256 为
`52cbda382f2ebf8fd55bf35079f62d035faa0cc16eb39c3538e5107be336738c`；这是本候选
运行时登记的源码，不随 E3-HALT-01 的后续控制流修复覆盖。

本轮保留 China81 原有的逐车场、逐车型最高数量，没有设置油电比例或新增车辆。
当前 E3 静态 HGS-SP 中一条入选路线占用一个车辆名额。
seed 1 的两种散乱客户分布都在搜索前触发容量下界：部分承包商名下客户总需求量已经超过其全部可用车辆的一次配送容量之和。
因此单干方案不可能合法，按用户停止条件未启动联合优化，也未启动 seeds 2--3。

| 分布 | 车场 | 客户需求/kg | 可用运力/kg | 硬缺口/kg |
|---|---:|---:|---:|---:|
| Uniform_Balanced | D_dongguan | 9164 | 8640 | 524 |
| Uniform_Balanced | D_foshan | 9446 | 8640 | 806 |
| Uniform_Unbalanced | D_dongguan | 16110 | 8640 | 7470 |
| Uniform_Unbalanced | D_foshan | 15350 | 8640 | 6710 |

`raw_runs.csv` 保留两种分布下的单干失败行和联合方案未运行行；成本、里程、排放与实际车型使用量为空，因为没有合法最终解。
