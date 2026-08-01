# E3 capacity-rank-aligned candidate pilot

**状态：HALT_CAPACITY_RANK_ALIGNED_CANDIDATE。**

映射在搜索前固定：源标签按其承接的 China81 总需求量从大到小排序，
原车场按 CV/EV 原始上限形成的总载重从大到小排序，再一一对应；
同值分别按标签号和 depot_id 排序。客户、需求、时窗、车型和车辆上限均未改变。

| 车场 | 源标签 | 客户数 | 需求/kg | 原运力/kg | CV上限 | EV上限 |
|---|---:|---:|---:|---:|---:|---:|
| D_dongguan | 3 | 20 | 5626 | 12075 | 5 | 2 |
| D_foshan | 2 | 20 | 4929 | 12075 | 5 | 2 |
| D_guangzhou | 0 | 80 | 21459 | 24185 | 11 | 3 |
| D_shenzhen | 1 | 80 | 22709 | 31090 | 14 | 4 |

| seed | 方案 | 实际CV | 实际EV | 成本/元 | 里程/km | 排放/kg | 跨承包商客户 | 联合相对单干/% | 状态 |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | HISTORICAL_STANDALONE |  |  |  |  |  |  |  | NOT_RUN_INPUT_OR_INITIAL_HALT |
| 1 | JOINT_OPTIMIZED |  |  |  |  |  |  |  | NOT_RUN_INPUT_OR_INITIAL_HALT |

这是用户批准后的正式面板成员。旧排序与 Uniform_Balanced 的 v1 容量失败证据保持原样。
