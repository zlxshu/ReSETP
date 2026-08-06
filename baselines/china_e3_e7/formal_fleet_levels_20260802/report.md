# XB 车队电动化五档正式实验（论文 5.2）

终态：`XB_FLEET_LEVELS_FORMAL_COMPLETE`。

## FACT：合同与执行

正式实例为 `cn-prd-100c-01-V2-LOCATIONS`；五档为 0/25/50/75/100%，每档种子 1--10，共 50 个正式配对单元。每个单元内部各运行一次碳盲与碳感知搜索，因此搜索臂执行数为 100。

多趟显式开启；固定成本按实际使用实体车计费，每辆 170 元；车场充电并发不设上限；逐场车队上限逐字读取 v3 authority 的 Hamilton 五档。

## FACT：五档结果（每档一行）

| EV档位 | 可用CV/EV | 可行配对 | 实派CV/EV（碳感知均值） | 实体车/路线（均值） | 相对碳盲排放差% | 充电时刻改变 | 车型改变客户 | 路线改变客户 | 不可行/未找到 | 违反项 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 0% | 13/0 | 10/10 | 10.000000/0.000000 | 10.000000/16.000000 | 0.000000 | 0 | 0 | 0 | 0 | 无 |
| 25% | 10/3 | 10/10 | 7.000000/3.000000 | 10.000000/16.000000 | 0.000000 | 0 | 0 | 0 | 0 | 无 |
| 50% | 6/7 | 10/10 | 4.000000/6.000000 | 10.000000/16.000000 | 0.000000 | 0 | 0 | 0 | 0 | 无 |
| 75% | 3/10 | 0/10 | NA/NA | NA/NA | NA | 0 | 0 | 0 | 10 | COST_ONLY: ValueError: China81 route skeleton cannot satisfy the registered physical fleet caps at 'D_guangzhou': overage=(2, 0, 0)；COST_PLUS_CARBON: ValueError: China81 route skeleton cannot satisfy the registered physical fleet caps at 'D_guangzhou': overage=(2, 0, 0) |
| 100% | 0/13 | 0/10 | NA/NA | NA/NA | NA | 0 | 0 | 0 | 10 | COST_ONLY: ValueError: China81 route skeleton cannot satisfy the registered physical fleet caps at 'D_guangzhou': overage=(3, 0, 0)；COST_PLUS_CARBON: ValueError: China81 route skeleton cannot satisfy the registered physical fleet caps at 'D_guangzhou': overage=(3, 0, 0) |

## DECISION：预注册否定条件核对

预注册否定条件触发：`FALSIFIER_NO_DECISION_RESPONSE`、`FALSIFIER_NO_CROSS_LEVEL_LAYER_SHIFT`、`FALSIFIER_SERVICE_OR_FEASIBILITY_CONFOUND`。
主张判定：`NOT_SUPPORTED_BY_ONE_OR_MORE_REGISTERED_FALSIFIERS`。该判定不影响不利结果和不可行档的保留。

## 证据边界

`raw_runs.csv` 每个档位--种子一行；`arm_runs.csv` 展开 100 个搜索臂；`fleet_level_summary.csv` 严格五行；`solutions/` 保存每个配对单元的完整双臂解。每行的 `solution_sha256` 是该双臂完整科学载荷的规范 JSON SHA-256，双臂解另有各自哈希。
充电时刻改变只统计可按路线、站点、能量和时长一一匹配的动作；无法匹配的动作单列，不被改写成时刻变化。车型和路线变化按客户计数，路线数与实体车数始终分列。
