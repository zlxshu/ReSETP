# E2-RERUN-UNIFIED-01 新车型可行性预检

裁决：`PASS_NEW_VEHICLE_PAIR_FEASIBILITY_PREFLIGHT`。九题完整可行=True；EV 承担客户比例中位数 32.50%，历史基线 7.8%。

| 算例 | 可行率 | EV客户占比 | EV路线占比 | 充电动作 | 电量/时窗/容量/车队违约 |
|---|---:|---:|---:|---:|---:|
| cn-cy-100c-01-V2-LOCATIONS | 100% | 30.00% | 29.41% | 5 | 0/0/0/0 |
| cn-cy-200c-01-V2-LOCATIONS | 100% | 32.50% | 28.12% | 9 | 0/0/0/0 |
| cn-cy-25c-01-V2-LOCATIONS | 100% | 28.00% | 25.00% | 1 | 0/0/0/0 |
| cn-jjj-100c-01-V2-LOCATIONS | 100% | 32.00% | 31.25% | 6 | 0/0/0/0 |
| cn-jjj-200c-01-V2-LOCATIONS | 100% | 33.50% | 30.30% | 10 | 0/0/0/0 |
| cn-jjj-25c-01-V2-LOCATIONS | 100% | 32.00% | 25.00% | 1 | 0/0/0/0 |
| cn-prd-100c-01-V2-LOCATIONS | 100% | 40.00% | 33.33% | 5 | 0/0/0/0 |
| cn-prd-200c-01-V2-LOCATIONS | 100% | 34.50% | 33.33% | 11 | 0/0/0/0 |
| cn-prd-25c-01-V2-LOCATIONS | 100% | 56.00% | 50.00% | 2 | 0/0/0/0 |

每题由三个视角各自独立跑到 NoImprovement(3000)，再经限时 MIP 路线池重组与 min() 安全网。
最终 witness 同时由 exact_china81_score 和直接 check_solution/evaluate 路径复核；失败行不删除。
本门只判断新车型对是否可进入正式统一批，不作五臂胜负或等算力主张。
