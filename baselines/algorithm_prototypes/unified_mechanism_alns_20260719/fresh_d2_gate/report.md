# 机制裁决双盆地 ALNS：D2 新组合开发门

- 结论：`STOP_DUAL_BASIN_MECHANISM_ALNS_D2`
- 范围：阶段一隔离开发；未进入阶段二，未启动正式实验。
- 数据：新组合三班完整模型包；原始 Goeke 文件并非首次出现。
- 最终裁决数据档：`primary`。
- 完整候选预算：每个带搜索臂 100 次。
- 公平边界：完整 ReSETP 候选评价数相同；总算力不相同。官方 HGS 的额外原生调用与墙钟单独报告。
- 每个完成臂另做 2 次只用于报告的完整成本复算。

## 成本与选择

| 数据档 | 实例 | 算法臂 | 成本 | 盆地 | 秒 | HGS原生调用 |
|---|---|---|---:|---|---:|---:|
| primary | DEV-DUAL-D2-GROUP456-SRC10-N21-DEP2 | current_project_pure_alns | 715.588523348 | - | 0.455 | 0 |
| primary | DEV-DUAL-D2-GROUP456-SRC10-N21-DEP2 | mechanism_alns_v7 | 628.085655129 | - | 0.482 | 0 |
| primary | DEV-DUAL-D2-GROUP456-SRC10-N21-DEP2 | mechanism_judged_dual_basin_alns | 628.085655129 | current_alns_warm | 0.646 | 2 |
| primary | DEV-DUAL-D2-GROUP456-SRC10-N21-DEP2 | mechanism_judged_dual_basin_no_mid_ablation | 628.085655129 | current_alns_warm | 0.509 | 2 |
| primary | DEV-DUAL-D2-GROUP456-SRC10-N21-DEP2 | official_hgs_route_source_plus_common_completion | 666.895718936 | - | 1.164 | 200 |
| primary | DEV-DUAL-D2-GROUP456-SRC10-N21-DEP2 | original_n_wouda_alns_plus_common_completion | 666.895718936 | - | 0.728 | 0 |
| primary | DEV-DUAL-D2-GROUP456-SRC10-N21-DEP2 | raw_cost_dual_basin_ablation | 628.085655129 | current_alns_warm | 0.643 | 2 |
| primary | DEV-DUAL-D2-GROUP789-SRC15-N34-DEP2 | current_project_pure_alns | 918.119767026 | - | 0.364 | 0 |
| primary | DEV-DUAL-D2-GROUP789-SRC15-N34-DEP2 | mechanism_alns_v7 | 873.806226625 | - | 0.632 | 0 |
| primary | DEV-DUAL-D2-GROUP789-SRC15-N34-DEP2 | mechanism_judged_dual_basin_alns | 883.702346697 | current_alns_warm | 0.986 | 2 |
| primary | DEV-DUAL-D2-GROUP789-SRC15-N34-DEP2 | mechanism_judged_dual_basin_no_mid_ablation | 873.806226625 | current_alns_warm | 0.708 | 2 |
| primary | DEV-DUAL-D2-GROUP789-SRC15-N34-DEP2 | official_hgs_route_source_plus_common_completion | 1003.751388361 | - | 2.976 | 200 |
| primary | DEV-DUAL-D2-GROUP789-SRC15-N34-DEP2 | original_n_wouda_alns_plus_common_completion | 1003.751388361 | - | 1.164 | 0 |
| primary | DEV-DUAL-D2-GROUP789-SRC15-N34-DEP2 | raw_cost_dual_basin_ablation | 883.702346697 | current_alns_warm | 0.976 | 2 |

## 预注册判断

- 对 `mechanism_alns_v7`：严格胜 0/2，中位改善 -0.566%。
- 对 `current_project_pure_alns`：严格胜 2/2，中位改善 7.988%。
- 对 `official_hgs_route_source_plus_common_completion`：严格胜 2/2，中位改善 8.890%。
- 对 `original_n_wouda_alns_plus_common_completion`：严格胜 2/2，中位改善 8.890%。
- 对 `raw_cost_dual_basin_ablation`：严格胜 0/2，中位改善 0.000%。
- 对 `mechanism_judged_dual_basin_no_mid_ablation`：严格胜 0/2，中位改善 -0.566%。
- `DEV-DUAL-D2-GROUP456-SRC10-N21-DEP2` 的候选/同题强对手中位墙钟比：1.067。
- `DEV-DUAL-D2-GROUP789-SRC15-N34-DEP2` 的候选/同题强对手中位墙钟比：1.098。
- 墙钟比中位数：1.082，每题及中位门槛均不超过 1.25。
- 中段机制校正：`FAILED_SAFETY_LIMIT`。

本报告只是一颗种子的开发门，不是论文性能结论。
