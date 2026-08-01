# E7-O1 重算路线低成本试验

本试验只比较何时重新计算剩余路线，不把触发解释为车辆立即发车。
订单采用 H0/G2 的06:00--22:00独立出现流；累计订单数门槛采用 Ninikas & Minis（2020，第14页）的10%与20%作低成本O1试验；33%经零算力检查无法早于30分钟上限触发，本轮不运行。
每阶段8次完整评价只用于低成本探路，不是正式预算。

| 算例 | 规则 | 合法 | 平均成本(元) | 平均里程(km) | 平均用车 | 平均触发/实际改路线 | 门槛/到时触发 | 平均等待(min) | 平均排放(kg) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| cn-prd-50c-01-V2-LOCATIONS | 逐单立即重算 | 3/3 | 3181.19 | 850.30 | 8.67 | 10.00/10.00 | 0.00/0.00 | 0.00 | 234.47 |
| cn-prd-50c-01-V2-LOCATIONS | 固定30分钟重算 | 3/3 | 3009.42 | 818.08 | 8.33 | 8.33/8.33 | 0.00/8.33 | 15.42 | 222.78 |
| cn-prd-50c-01-V2-LOCATIONS | 累计10%订单或最多30分钟重算 | 3/3 | 3181.19 | 850.30 | 8.67 | 10.00/10.00 | 10.00/0.00 | 0.00 | 234.47 |
| cn-prd-50c-01-V2-LOCATIONS | 累计20%订单或最多30分钟重算 | 3/3 | 3099.50 | 837.35 | 8.67 | 8.67/8.67 | 1.33/7.33 | 13.40 | 229.28 |
| cn-prd-100c-02-V2-LOCATIONS | 逐单立即重算 | 3/3 | 7527.12 | 1901.49 | 16.67 | 20.00/20.00 | 0.00/0.00 | 0.00 | 545.56 |
| cn-prd-100c-02-V2-LOCATIONS | 固定30分钟重算 | 3/3 | 7303.65 | 1929.80 | 17.00 | 12.67/12.67 | 0.00/12.67 | 15.78 | 558.76 |
| cn-prd-100c-02-V2-LOCATIONS | 累计10%订单或最多30分钟重算 | 3/3 | 7704.04 | 2027.54 | 16.67 | 13.00/13.00 | 7.00/6.00 | 7.64 | 593.38 |
| cn-prd-100c-02-V2-LOCATIONS | 累计20%订单或最多30分钟重算 | 3/3 | 7131.63 | 1895.76 | 17.67 | 12.67/12.67 | 0.33/12.33 | 15.42 | 547.39 |
| cn-prd-150c-01-V2-LOCATIONS | 逐单立即重算 | 3/3 | 9470.69 | 2960.12 | 22.33 | 30.00/30.00 | 0.00/0.00 | 0.00 | 872.57 |
| cn-prd-150c-01-V2-LOCATIONS | 固定30分钟重算 | 2/3 | 10553.74 | 3168.77 | 23.00 | 13.50/13.50 | 0.00/13.50 | 16.47 | 941.36 |
| cn-prd-150c-01-V2-LOCATIONS | 累计10%订单或最多30分钟重算 | 3/3 | 10151.17 | 3089.91 | 23.33 | 16.33/16.33 | 5.00/11.33 | 9.75 | 917.13 |
| cn-prd-150c-01-V2-LOCATIONS | 累计20%订单或最多30分钟重算 | 2/3 | 10553.74 | 3168.77 | 23.00 | 13.50/13.50 | 0.00/13.50 | 16.47 | 941.36 |

配对差值均为左方案减右方案；全部逐行结果保存在CSV，不根据方向删行。

| 算例 | 左方案 vs 右方案 | 平均成本差 | 平均里程差 | 平均用车差 | 平均实际改路线差 | 平均等待差 | 平均排放差 |
|---|---|---:|---:|---:|---:|---:|---:|
| cn-prd-50c-01-V2-LOCATIONS | 逐单立即重算 vs 固定30分钟重算 | +4.75% | +3.40% | +0.33 | +1.67 | -15.42 | +4.43% |
| cn-prd-50c-01-V2-LOCATIONS | 逐单立即重算 vs 累计10%订单或最多30分钟重算 | +0.00% | +0.00% | +0.00 | +0.00 | +0.00 | +0.00% |
| cn-prd-50c-01-V2-LOCATIONS | 逐单立即重算 vs 累计20%订单或最多30分钟重算 | +1.54% | +0.93% | +0.00 | +1.33 | -13.40 | +1.27% |
| cn-prd-50c-01-V2-LOCATIONS | 固定30分钟重算 vs 累计10%订单或最多30分钟重算 | -4.17% | -3.05% | -0.33 | -1.67 | +15.42 | -3.96% |
| cn-prd-50c-01-V2-LOCATIONS | 固定30分钟重算 vs 累计20%订单或最多30分钟重算 | -3.23% | -2.51% | -0.33 | -0.33 | +2.02 | -3.16% |
| cn-prd-50c-01-V2-LOCATIONS | 累计10%订单或最多30分钟重算 vs 累计20%订单或最多30分钟重算 | +1.54% | +0.93% | +0.00 | +1.33 | -13.40 | +1.27% |
| cn-prd-100c-02-V2-LOCATIONS | 逐单立即重算 vs 固定30分钟重算 | +4.62% | +0.09% | -0.33 | +7.33 | -15.78 | -0.10% |
| cn-prd-100c-02-V2-LOCATIONS | 逐单立即重算 vs 累计10%订单或最多30分钟重算 | -1.50% | -4.87% | +0.00 | +7.00 | -7.64 | -6.14% |
| cn-prd-100c-02-V2-LOCATIONS | 逐单立即重算 vs 累计20%订单或最多30分钟重算 | +6.97% | +1.77% | -1.00 | +7.33 | -15.42 | +1.80% |
| cn-prd-100c-02-V2-LOCATIONS | 固定30分钟重算 vs 累计10%订单或最多30分钟重算 | -5.36% | -4.95% | +0.33 | -0.33 | +8.14 | -6.01% |
| cn-prd-100c-02-V2-LOCATIONS | 固定30分钟重算 vs 累计20%订单或最多30分钟重算 | +2.21% | +1.68% | -0.67 | +0.00 | +0.36 | +1.91% |
| cn-prd-100c-02-V2-LOCATIONS | 累计10%订单或最多30分钟重算 vs 累计20%订单或最多30分钟重算 | +8.11% | +7.02% | -1.00 | +0.33 | -7.78 | +8.56% |
| cn-prd-150c-01-V2-LOCATIONS | 逐单立即重算 vs 固定30分钟重算 | -10.98% | -7.22% | -1.50 | +16.50 | -16.47 | -7.82% |
| cn-prd-150c-01-V2-LOCATIONS | 逐单立即重算 vs 累计10%订单或最多30分钟重算 | -6.67% | -3.75% | -1.00 | +13.67 | -9.75 | -4.19% |
| cn-prd-150c-01-V2-LOCATIONS | 逐单立即重算 vs 累计20%订单或最多30分钟重算 | -10.98% | -7.22% | -1.50 | +16.50 | -16.47 | -7.82% |
| cn-prd-150c-01-V2-LOCATIONS | 固定30分钟重算 vs 累计10%订单或最多30分钟重算 | +5.33% | +5.76% | +0.00 | -2.00 | +6.72 | +6.39% |
| cn-prd-150c-01-V2-LOCATIONS | 固定30分钟重算 vs 累计20%订单或最多30分钟重算 | +0.00% | +0.00% | +0.00 | +0.00 | +0.00 | +0.00% |
| cn-prd-150c-01-V2-LOCATIONS | 累计10%订单或最多30分钟重算 vs 累计20%订单或最多30分钟重算 | -5.05% | -5.32% | +0.00 | +2.00 | -6.72 | -5.83% |

逐单元完整结果（失败单元不删除）：

| 算例 | seed | 规则 | 状态 | 成本(元) | 里程(km) | 用车 | 实际改路线 | 平均等待(min) | 排放(kg) | 失败原文 |
|---|---:|---|---|---:|---:|---:|---:|---:|---:|---|
| cn-prd-100c-02-V2-LOCATIONS | 1 | 逐单立即重算 | PASS_ACCEPT_ALL | 6264.80 | 1668.17 | 16.00 | 20.00 | 0.00 | 468.86 |  |
| cn-prd-100c-02-V2-LOCATIONS | 1 | 固定30分钟重算 | PASS_ACCEPT_ALL | 7640.58 | 2063.60 | 17.00 | 12.00 | 17.31 | 605.43 |  |
| cn-prd-100c-02-V2-LOCATIONS | 1 | 累计10%订单或最多30分钟重算 | PASS_ACCEPT_ALL | 7773.10 | 2226.52 | 16.00 | 13.00 | 8.58 | 668.03 |  |
| cn-prd-100c-02-V2-LOCATIONS | 1 | 累计20%订单或最多30分钟重算 | PASS_ACCEPT_ALL | 7640.58 | 2063.60 | 17.00 | 12.00 | 17.31 | 605.43 |  |
| cn-prd-100c-02-V2-LOCATIONS | 2 | 逐单立即重算 | PASS_ACCEPT_ALL | 8784.17 | 2136.07 | 16.00 | 20.00 | 0.00 | 623.16 |  |
| cn-prd-100c-02-V2-LOCATIONS | 2 | 固定30分钟重算 | PASS_ACCEPT_ALL | 8286.00 | 2132.78 | 16.00 | 11.00 | 15.43 | 628.25 |  |
| cn-prd-100c-02-V2-LOCATIONS | 2 | 累计10%订单或最多30分钟重算 | PASS_ACCEPT_ALL | 8784.56 | 2135.86 | 16.00 | 13.00 | 5.35 | 623.36 |  |
| cn-prd-100c-02-V2-LOCATIONS | 2 | 累计20%订单或最多30分钟重算 | PASS_ACCEPT_ALL | 7769.93 | 2030.66 | 18.00 | 11.00 | 14.34 | 594.13 |  |
| cn-prd-100c-02-V2-LOCATIONS | 3 | 逐单立即重算 | PASS_ACCEPT_ALL | 7532.40 | 1900.24 | 18.00 | 20.00 | 0.00 | 544.66 |  |
| cn-prd-100c-02-V2-LOCATIONS | 3 | 固定30分钟重算 | PASS_ACCEPT_ALL | 5984.37 | 1593.01 | 18.00 | 15.00 | 14.62 | 442.60 |  |
| cn-prd-100c-02-V2-LOCATIONS | 3 | 累计10%订单或最多30分钟重算 | PASS_ACCEPT_ALL | 6554.45 | 1720.25 | 18.00 | 13.00 | 8.99 | 488.76 |  |
| cn-prd-100c-02-V2-LOCATIONS | 3 | 累计20%订单或最多30分钟重算 | PASS_ACCEPT_ALL | 5984.37 | 1593.01 | 18.00 | 15.00 | 14.62 | 442.60 |  |
| cn-prd-150c-01-V2-LOCATIONS | 1 | 逐单立即重算 | PASS_ACCEPT_ALL | 9360.89 | 2960.94 | 23.00 | 30.00 | 0.00 | 871.09 |  |
| cn-prd-150c-01-V2-LOCATIONS | 1 | 固定30分钟重算 | PASS_ACCEPT_ALL | 10636.54 | 3298.09 | 23.00 | 12.00 | 18.12 | 988.82 |  |
| cn-prd-150c-01-V2-LOCATIONS | 1 | 累计10%订单或最多30分钟重算 | PASS_ACCEPT_ALL | 10198.43 | 3236.75 | 23.00 | 14.00 | 9.34 | 971.03 |  |
| cn-prd-150c-01-V2-LOCATIONS | 1 | 累计20%订单或最多30分钟重算 | PASS_ACCEPT_ALL | 10636.54 | 3298.09 | 23.00 | 12.00 | 18.12 | 988.82 |  |
| cn-prd-150c-01-V2-LOCATIONS | 2 | 逐单立即重算 | PASS_ACCEPT_ALL | 9426.49 | 2910.96 | 20.00 | 30.00 | 0.00 | 860.55 |  |
| cn-prd-150c-01-V2-LOCATIONS | 2 | 固定30分钟重算 | PASS_ACCEPT_ALL | 10470.94 | 3039.44 | 23.00 | 15.00 | 14.82 | 893.90 |  |
| cn-prd-150c-01-V2-LOCATIONS | 2 | 累计10%订单或最多30分钟重算 | PASS_ACCEPT_ALL | 9843.63 | 2772.77 | 23.00 | 17.00 | 10.17 | 805.67 |  |
| cn-prd-150c-01-V2-LOCATIONS | 2 | 累计20%订单或最多30分钟重算 | PASS_ACCEPT_ALL | 10470.94 | 3039.44 | 23.00 | 15.00 | 14.82 | 893.90 |  |
| cn-prd-150c-01-V2-LOCATIONS | 3 | 逐单立即重算 | PASS_ACCEPT_ALL | 9624.70 | 3008.46 | 24.00 | 30.00 | 0.00 | 886.09 |  |
| cn-prd-150c-01-V2-LOCATIONS | 3 | 固定30分钟重算 | HALT_STAGE_FAILURE | NA | NA | NA | 17.00 | 11.98 | NA | NoExecutableContinuation: stage search found no executable continuation (initial_feasible=False, changed=3, executable=0, accepted=0, top_rejections=[('E7_DYNAMIC_MULTITRIP_V1: no inherited asset can serve open route REPACK_001', 2), ('E7_DYNAMIC_MULTITRIP_V1: no inherited asset can serve open route DYN_EVENT_C135', 1)]) |
| cn-prd-150c-01-V2-LOCATIONS | 3 | 累计10%订单或最多30分钟重算 | PASS_ACCEPT_ALL | 10411.46 | 3260.22 | 24.00 | 18.00 | 9.76 | 974.70 |  |
| cn-prd-150c-01-V2-LOCATIONS | 3 | 累计20%订单或最多30分钟重算 | HALT_STAGE_FAILURE | NA | NA | NA | 17.00 | 11.98 | NA | NoExecutableContinuation: stage search found no executable continuation (initial_feasible=False, changed=3, executable=0, accepted=0, top_rejections=[('E7_DYNAMIC_MULTITRIP_V1: no inherited asset can serve open route REPACK_001', 2), ('E7_DYNAMIC_MULTITRIP_V1: no inherited asset can serve open route DYN_EVENT_C135', 1)]) |
| cn-prd-50c-01-V2-LOCATIONS | 1 | 逐单立即重算 | PASS_ACCEPT_ALL | 2548.87 | 719.15 | 9.00 | 10.00 | 0.00 | 192.02 |  |
| cn-prd-50c-01-V2-LOCATIONS | 1 | 固定30分钟重算 | PASS_ACCEPT_ALL | 2542.09 | 720.29 | 8.00 | 8.00 | 14.19 | 189.59 |  |
| cn-prd-50c-01-V2-LOCATIONS | 1 | 累计10%订单或最多30分钟重算 | PASS_ACCEPT_ALL | 2548.87 | 719.15 | 9.00 | 10.00 | 0.00 | 192.02 |  |
| cn-prd-50c-01-V2-LOCATIONS | 1 | 累计20%订单或最多30分钟重算 | PASS_ACCEPT_ALL | 2828.35 | 787.44 | 9.00 | 8.00 | 9.84 | 212.20 |  |
| cn-prd-50c-01-V2-LOCATIONS | 2 | 逐单立即重算 | PASS_ACCEPT_ALL | 4139.99 | 1040.73 | 9.00 | 10.00 | 0.00 | 303.18 |  |
| cn-prd-50c-01-V2-LOCATIONS | 2 | 固定30分钟重算 | PASS_ACCEPT_ALL | 3626.75 | 940.25 | 9.00 | 8.00 | 14.61 | 269.61 |  |
| cn-prd-50c-01-V2-LOCATIONS | 2 | 累计10%订单或最多30分钟重算 | PASS_ACCEPT_ALL | 4139.99 | 1040.73 | 9.00 | 10.00 | 0.00 | 303.18 |  |
| cn-prd-50c-01-V2-LOCATIONS | 2 | 累计20%订单或最多30分钟重算 | PASS_ACCEPT_ALL | 3610.73 | 930.92 | 9.00 | 9.00 | 13.54 | 266.52 |  |
| cn-prd-50c-01-V2-LOCATIONS | 3 | 逐单立即重算 | PASS_ACCEPT_ALL | 2854.69 | 791.01 | 8.00 | 10.00 | 0.00 | 208.21 |  |
| cn-prd-50c-01-V2-LOCATIONS | 3 | 固定30分钟重算 | PASS_ACCEPT_ALL | 2859.41 | 793.69 | 8.00 | 9.00 | 17.46 | 209.14 |  |
| cn-prd-50c-01-V2-LOCATIONS | 3 | 累计10%订单或最多30分钟重算 | PASS_ACCEPT_ALL | 2854.69 | 791.01 | 8.00 | 10.00 | 0.00 | 208.21 |  |
| cn-prd-50c-01-V2-LOCATIONS | 3 | 累计20%订单或最多30分钟重算 | PASS_ACCEPT_ALL | 2859.41 | 793.69 | 8.00 | 9.00 | 16.83 | 209.14 |  |

未跑通单元的原始停止信息：

- cn-prd-150c-01-V2-LOCATIONS，seed 3，固定30分钟重算，第18次重算：NoExecutableContinuation: stage search found no executable continuation (initial_feasible=False, changed=3, executable=0, accepted=0, top_rejections=[('E7_DYNAMIC_MULTITRIP_V1: no inherited asset can serve open route REPACK_001', 2), ('E7_DYNAMIC_MULTITRIP_V1: no inherited asset can serve open route DYN_EVENT_C135', 1)])
- cn-prd-150c-01-V2-LOCATIONS，seed 3，累计20%订单或最多30分钟重算，第18次重算：NoExecutableContinuation: stage search found no executable continuation (initial_feasible=False, changed=3, executable=0, accepted=0, top_rejections=[('E7_DYNAMIC_MULTITRIP_V1: no inherited asset can serve open route REPACK_001', 2), ('E7_DYNAMIC_MULTITRIP_V1: no inherited asset can serve open route DYN_EVENT_C135', 1)])

本报告只交付完整低成本结果。是否形成论文效应、继续扩大O1或转入O2，依据全部结果另行判断。
