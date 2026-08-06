# D3B：D3 `third_occurrence` 复议

- 任务编号：`D3B`
- 终态：`D3B_REBUTTAL_COMPLETE`
- 复议对象：`docs/handoff/diagnosis_20260802/d3_rootcause/`

## 结论先行

| 问题 | 复议结论 | 直接证据 |
|---|---|---|
| 仓库是否存在“1.48%” | **存在** | `baselines/china_e3_e7/e3_zone_joint_20260731/decision.json`：`overall_cost_effect_pct_joint_vs_zone=1.4829370445427614`、`formal_units_run=40` |
| 1.48% 与 −0.038% 是否为同一件事的两次测量 | **不是，是两个不同对照** | 前者为 `JOINT 相对 ZONE`；后者为 `POOLED 相对 JOINT`。臂定义见 `baselines/china_e3_e7/e3_pooling_probe_20260731/isolated_copy/probe_pooling.py`：`ZONE=(hard_home_depot_lock=true,pool_fleet=false)`、`JOINT=(false,false)`、`POOLED=(false,true)` |
| `third_occurrence` | **由 `false` 改为 `true`** | 王勇等（2023）pp.1134、1137--1139 的比较固定客户归属、改变车辆/充电站共享；本项目旧 E3 只解除客户归属硬锁、保留逐车场车队上限。该错位在冻结情景前通过文献—实验臂逐项映射即可发现 |
| 2026-08-01 正式 E3 实际测量对象 | **修复一次人为随机打散，不是解除经验意义上的历史归属约束** | `source_p_sequences.csv` 为 6 条 `Uniform_Balanced/Uniform_Unbalanced` 标签序列；正式包 `candidate_family=Uniform_Unbalanced_Capacity_Rank_Aligned`；处理臂平均改派 `121.583333/175=69.4762%`，基准臂 `60/60` 行均为 0 |

## 第一点：“1.48%”是否存在，以及它与 −0.038% 的关系

### FACT 1：1.48% 在仓库中有完整结果包

结果包是 `baselines/china_e3_e7/e3_zone_joint_20260731/`。

- `decision.json`：`overall_cost_effect_pct_joint_vs_zone=1.4829370445427614`，聚合字段为 `overall_aggregation="equal-weight arithmetic mean of the two per-instance effects"`，正式单元数 `formal_units_run=40`。
- 同一文件的两条实例结果为：50 客户算例 `cost_effect_pct_joint_vs_zone=2.2727594138817997`，100 客户算例 `cost_effect_pct_joint_vs_zone=0.693114675203723`；两者等权平均即 `1.4829370445427614`。
- `done.json` 再次登记 `cost_effect_pct_joint_vs_zone=1.4829370445427614`、`status="COMPLETE"`、`instances_completed=["cn-prd-50c-01-V2-LOCATIONS","cn-prd-100c-02-V2-LOCATIONS"]`。
- `report.md` 的对照定义是：ZONE 使用既定客户—车场映射并加硬锁；JOINT 使用相同映射和共同初解，但移除服务归属硬锁。两臂的逐车场车队上限不变。

**判断：** 记忆中的“1.48%”查有实据，来源不是 2026-08-01 的六算例正式 E3，而是 2026-07-31 的 `e3_zone_joint_20260731` 两算例、两臂、10 种子结果包。

### FACT 2：−0.038% 是另一个增量开关

`baselines/china_e3_e7/e3_pooling_probe_20260731/isolated_copy/probe_pooling.py` 明确写出三个臂：

| 臂 | 客户归属硬锁 | 逐车场车队约束是否池化 | 对照含义 |
|---|---:|---:|---|
| ZONE | `hard_home_depot_lock=true` | `pool_fleet=false` | 客户必须由所属车场服务，车队逐场锁定 |
| JOINT | `hard_home_depot_lock=false` | `pool_fleet=false` | 可重分客户，但车队仍逐场锁定 |
| POOLED | `hard_home_depot_lock=false` | `pool_fleet=true` | 在 JOINT 基础上再撤掉逐车场车辆数约束，只保留全局 CV/EV 总量 |

`probe_results.json` 的同种子成本为：

| seed | JOINT | POOLED | POOLED 相对 JOINT 节省率 |
|---:|---:|---:|---:|
| 1 | 2289.318598837748 | 2290.1857525902215 | −0.03787824695582147% |
| 2 | 2288.011934963608 | 2288.011934963608 | 0.00000000000000000% |
| 3 | 2288.011934963608 | 2288.840466684108 | −0.03621186182812346% |

**判断：** 两个数字不是同一件事的复测。`1.482937%` 测的是“解除客户服务归属硬锁”相对“保留该硬锁”；约 `−0.038%/0/−0.036%` 测的是“在已经解除客户硬锁后，再池化逐车场车队上限”。池化探针与旧正式结果共享 50 客户算例和 seeds 1--3 的一部分输入，但改变的实验开关不同。

## 第二点：`third_occurrence` 复议

复议使用 D3 自己给出的共同失误动作：

> 在冻结研究主张与情景前，没有把文献给出的机制必要条件逐项映射到候选算例，并用零搜索检查这些必要条件的可行集合是否非空。

### 第 (1) 次：非线性充电——共享该失误动作

`docs/handoff/diagnosis_20260802/d3_rootcause/verdict.json` 登记：`route_count=1040`、`route_energy_share_of_77_28kwh_max_pct=85.78012552541837`、`just_enough_public_stops=0`、`max_coverage_stop_saving_routes=0`；而文献车型参照为 `wang_74_8kwh_95km_routes_over_range=425/1040`。Wang et al. (2026) 的 `74.8 kWh/95 km` 见 PDF pp.24、26--27。

**判断：** 文献需要途中补电/进入曲线作用区，候选路线—车型组合却使该机会集合为空；冻结前的能耗/电池比例零搜索即可发现。第 (1) 次共享该动作。

### 第 (2) 次：动态订单——共享该失误动作

`docs/handoff/diagnosis_20260802/d3_rootcause/verdict.json` 登记：`waiting_loss_candidate_count=15`、`waiting_loss_usable_count=0`。倪冠群等（2025）pp.3875--3876 的等待项使用归一化 `c=1`；Gautam & Geunes (2024) pp.97、99、101--102 的 `h=0.6/1.2/2.4`、`phi=100` 是情景参数，不是可直接并入 China81 人民币目标的企业标定值。

**判断：** 研究问题先冻结为人民币经济发车，之后才发现必要的同语义人民币等待损失系数无法从已核来源实例化；冻结前核对单位与标定方法即可发现。第 (2) 次共享该动作。

### 第 (3) 次：客户归属重分——补齐记忆后也共享该失误动作

王勇等（2023）的必要机制与本项目实验开关并不相同：

- 王勇等（2023）p.1134 表7在 Case1--Case5 比较前已经用 3D-K-means 固定 DC1--DC4 的客户归属为 `33/33/42/38`；pp.1137--1139 的 Case1--Case5 改变的是车辆与充电站的共享程度，表13成本 `10992.7→6240.5`，车辆 `25→11`，结论为成本降低 `43.2%`、车辆减少 `56.0%`。
- `docs/handoff/mechanism_lever_rethink_20260731/report.md` 第 2.2 节核对本项目旧 E3：ZONE/JOINT 加载同一 bundle，`fleet_caps_by_depot` 在两臂完全相同，唯一差异开关为 `hard_home_depot_lock`；车辆仍绑定车场，只有客户服务归属被放开。
- `baselines/china_e3_e7/e3_pooling_probe_20260731/isolated_copy/probe_pooling.py` 也把旧 JOINT 精确定义为 `hard_home_depot_lock=false,pool_fleet=false`，说明王勇式逐车场车队池化不在旧 JOINT 的动作集合内。

**判断：** 若以王勇的 `43.2%/56.0%` 作为杠杆依据，冻结前逐项映射“文献改变什么—本项目实验臂改变什么”，会立即得到“文献固定客户归属并开放车队共享，本项目开放客户归属却固定逐场车队”的错位；零搜索读取臂配置即可得到旧 JOINT 中 `pool_fleet=false`。第 (3) 次因此共享同一个失误动作。

### 独立反证为什么不再维持 `false`

两条独立反证都成立，但它们回答的是“车队池化是否充分、是否普适”，不是“实验臂是否对齐所引用文献的机制”。

- `e3_pooling_probe_20260731/probe_results.json` 的 `−0.037878%/0/−0.036212%` 说明：在该 50 客户算例、三种子下，补上 `pool_fleet=true` 没有产生收益。它证伪“补车队池化必然救出大效应”，不改变旧 JOINT 的确没有测试该开关这一事实。
- 陈雨蝶等（2025）p.16 表9显示独立→分区成本已降 `31.18%`，分区→联合仅追加 `3.44%`。它说明客户分区可能贡献大头、资源共享未必贡献大头，与王勇方向冲突；也正因为文献机制不统一，冻结前更应先明确本项目究竟照哪篇文献、测试哪个开关。

**修订判定：`third_occurrence=true`。** 改判原因不是“补齐记忆后证明车队池化在本项目有效”，而是补齐记忆后判据回到共同失误动作本身：第 (3) 次同样没有在冻结主张和情景前完成文献机制—实验开关映射。D3 原判把“池化不是充分/普适杠杆”误当成了“没有发生机制映射失误”。

## 第三点：正式 E3 测的是历史约束解除，还是修复人为随机打散

### FACT 1：所谓“历史归属”没有 China81 历史记录来源

- `baselines/china_e3_e7/e3_scattered_ownership_20260801/source_p_sequences.csv` 含表头和 **6 条数据行**；`source_family` 仅为 `Uniform_Balanced`、`Uniform_Unbalanced`，各 3 个 replicate，每条 `p_sequence` 为 200 个 `0/1/2/3` 标签。
- `run_e3_scattered_ownership.py` 的 `sequences()` 硬检查 `len(rows)=6` 且每条长度 `200`；`prepare()` 按 China81 `customer_id` 排序后，把这些标签直接映射到四个车场。
- 正式入口 `run_e3_capacity_rank_aligned.py` 固定 `SOURCE_FAMILY="Uniform_Unbalanced"`、`FAMILY="Uniform_Unbalanced_Capacity_Rank_Aligned"`，再按标签组总需求与车场载重能力排序配对。
- 同目录 `README.md` 明确：只导入公开 `p` 所有权序列，不导入源数据的客户坐标；China81 的客户位置、需求、时间窗和逐车场 CV/EV 上限保持原值。故标签与 China81 的真实客户—承包商历史没有观测对应关系。

### FACT 2：正式处理不是边际松绑，而是大规模重排

`formal_panel_solomon_i1_20260801/panel_summary/decision.json` 登记：`source_rows=120`、`paired_units=60`、`mean_joint_cross_contractor_customer_count=121.58333333333333`、`mean_cost_reduction_pct=36.477268811132966`。

对六个成员包 `raw_runs.csv` 的 120 行按 `arm` 复算：

- `HISTORICAL_STANDALONE`：60 行，`cross_contractor_customer_count` 的唯一值为 `0`；
- `JOINT_OPTIMIZED`：60 行，均值 `121.58333333333333`；
- 六个算例为三个 150 客户和三个 200 客户算例，平均客户数 `(3×150+3×200)/6=175`；
- 改派比例为 `121.58333333333333/175=0.6947619047619047`，即 **69.4762%**。

**判断：** 代码形式上确实是“锁住标签”与“解除标签硬锁”的对照；但这些标签是从公开合成 Uniform 序列移植并按容量对齐的，不是 China81 企业历史归属。因此科学上测得的是**解除人为随机打散并让算法重新理顺客户—车场关系的情景效应**，不是解除真实历史归属约束的经验效应。

### 对第二点的反作用

**它支持 `third_occurrence=true`，同时校正第 (3) 次的精确病灶。** `panel_summary/decision.json` 的 `121.583333/175=69.4762%` 证明“客户重指派”自身的动作集合不仅非空，而且被大幅激活；所以第 (3) 次不能再描述为“客户重指派没有显形空间”。真正的共同失误是：`run_e3_capacity_rank_aligned.py` 让 `hard_home_depot_lock` 成为唯一处理开关，同时仍保留逐车场车队上限，却没有先把王勇等（2023）pp.1134、1137--1139 的固定客户归属/车队共享机制映射到实验臂。人为随机打散把另一个杠杆放大到 69.5%，反而使这一构念错位更清楚。

`status = D3B_REBUTTAL_COMPLETE`
