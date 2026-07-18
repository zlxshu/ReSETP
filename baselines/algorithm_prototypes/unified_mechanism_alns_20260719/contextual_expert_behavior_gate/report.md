# 当前病灶驱动精确专家：0/1/2/5 行为门

结论：`PASS_CONTEXT_GATED_EXPERT_BEHAVIOUR`。

| 机制 | 状态 | B | 机制收费 | 普通收费 | 接受 | 越界 | 预算闭合 |
|---|---|---:|---:|---:|---:|---:|---|
| multi_depot_responsibility | binding | 0 | 0 | 0 | 0 | 0 | True |
| multi_depot_responsibility | binding | 1 | 1 | 0 | 1 | 0 | True |
| multi_depot_responsibility | binding | 2 | 1 | 1 | 1 | 0 | True |
| multi_depot_responsibility | binding | 5 | 1 | 4 | 1 | 0 | True |
| multi_depot_responsibility | nonbinding | 0 | 0 | 0 | 0 | 0 | True |
| multi_depot_responsibility | nonbinding | 1 | 0 | 1 | 0 | 0 | True |
| multi_depot_responsibility | nonbinding | 2 | 0 | 2 | 0 | 0 | True |
| multi_depot_responsibility | nonbinding | 5 | 0 | 5 | 0 | 0 | True |
| fleet_charge | binding | 0 | 0 | 0 | 0 | 0 | True |
| fleet_charge | binding | 1 | 1 | 0 | 1 | 0 | True |
| fleet_charge | binding | 2 | 1 | 1 | 1 | 0 | True |
| fleet_charge | binding | 5 | 1 | 4 | 1 | 0 | True |
| fleet_charge | nonbinding | 0 | 0 | 0 | 0 | 0 | True |
| fleet_charge | nonbinding | 1 | 0 | 1 | 0 | 0 | True |
| fleet_charge | nonbinding | 2 | 0 | 2 | 0 | 0 | True |
| fleet_charge | nonbinding | 5 | 0 | 5 | 0 | 0 | True |
| carbon_time | binding | 0 | 0 | 0 | 0 | 0 | True |
| carbon_time | binding | 1 | 1 | 0 | 1 | 0 | True |
| carbon_time | binding | 2 | 1 | 1 | 1 | 0 | True |
| carbon_time | binding | 5 | 1 | 4 | 1 | 0 | True |
| carbon_time | nonbinding | 0 | 0 | 0 | 0 | 0 | True |
| carbon_time | nonbinding | 1 | 0 | 1 | 0 | 0 | True |
| carbon_time | nonbinding | 2 | 0 | 2 | 0 | 0 | True |
| carbon_time | nonbinding | 5 | 0 | 5 | 0 | 0 | True |

本门只证明三位专家在绑定状态下能形成一个有归属、可行且严格改善的共同评分候选，在不绑定状态下不收费，并且搜索始终只有一条连续轨迹。它不证明候选算法比任何 ALNS 或 HGS 更强，也不授权阶段二或正式全量实验。
