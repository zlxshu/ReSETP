# E5-B2：Wang 95 km 续航参照下的零搜索机会审计

81 个权威见证算例共有 1040 条既定路线。按电动车路网距离复算，其中 425 条超过 Wang 等（2026）北京业务案例的 95 km 续航参照，占 40.87%。

这里没有把 95 km 或该文献车辆写入 China81 求解器，也没有替换原 77.28 kWh 车型。它只回答一个问题：若把文献车辆作为敏感性参照，现成路线中有多少条在物理上可能需要途中补电。

| 正式算例 | 路线数 | 超过95 km | 比例 | 最长路线(km) |
|---|---:|---:|---:|---:|
| cn-prd-150c-01-V2-LOCATIONS | 27 | 3 | 11.11% | 101.934 |
| cn-prd-150c-02-V2-LOCATIONS | 27 | 3 | 11.11% | 113.202 |
| cn-prd-150c-03-V2-LOCATIONS | 26 | 6 | 23.08% | 115.645 |
| cn-prd-200c-01-V2-LOCATIONS | 35 | 7 | 20.00% | 113.354 |
| cn-prd-200c-02-V2-LOCATIONS | 36 | 6 | 16.67% | 107.472 |
| cn-prd-200c-03-V2-LOCATIONS | 36 | 6 | 16.67% | 104.115 |

这不是非线性充电效应，也不能替代 E5-B2 的车型、路径、充电站、充电次数和充电量联合优化。即使一条路线超过 95 km，也仍需联合优化判断能否补电、在哪里补、补多少以及成本是否改善。

文献依据：Wang et al. (2026), Computers & Operations Research, PDF pp. 24, 26-27; repository review: docs/handoff/e5b_literature_and_infrastructure_diagnosis_20260801.md:84-92。本产物 formal_result=false。
