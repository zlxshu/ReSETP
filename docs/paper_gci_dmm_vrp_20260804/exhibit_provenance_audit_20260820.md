# 论文 v2 版 15 个图表的数据出处与算例身份审计

## 最要紧的三件事

1. 当前已填写的私有算例数字，没有查到来自 `GZ-FS`、`PRDFIX`、`METRO`、`DEPOTSWAP` 或 `V3-TWO-SHIFT` 旧分支；能追到算例的已填私有数字均指向 `cn-jjj-50c-01-DEPOTSEARCH-d996f755bd`。表2的 PR11A--PR24B 是公开基准题，按设计就不是统一私有算例，也不是上述退役分支。
2. 15 件展品中，图1、图2、图4是明确的占位壳，图5是无算例身份的概念示意图；表6和表8整表留白。仓库虽有统一算例上的技术探针，但不满足这两张表现有的正式比较口径。
3. 名为 `china81_final_suite_v2_20260815` 的目录实际有 **82** 个算例；元数据也登记 `instance_count=82`。原 81 例中有 52 个目录名带 `V3-TWO-SHIFT`，统一主算例是额外加入的第 82 个。

## 审计口径与快照

- 本报告只读检查仓库；未运行求解器、实验或 Git 命令。
- 除明确标为“出处不明/未查清”的项目外，下列表格中的计数和文件读数均为 `FACT`；由事实作出的用途判断写成“判定”，缺证据处保留为 `UNKNOWN`，不补猜测。
- 论文快照：`main.tex` SHA-256 为 `8ebe8407cbd0f889d7a2071e83880a16dcfb97f400b6b4e348185020c0c3464b`；`sections/model_algorithm_experiments.tex` 为 `75d99d2a86632a232e8604ae48f34af8e93b1926177490f62c0b9e12146e1d25`；`build_approved_figures.py` 为 `63d5470fb377a12a00b8e3b6d93bddbdb42abb9ceccddafd19941e42ff4b85fe`。
- “真数格”按表格中的数值结果单元格计数；一个格内的 `0.5633/0.8364/1.1486` 或 `18/2` 仍算一个格。客户编号、车型名和路线字符串不算“真数格”。表2表头里的两个 `\TBD{}` 也占表格单元格，计入占位格。
- 图不硬套表格计数；改报“有无真实数据曲线/条带”。JSON 证据给字段路径，CSV 证据给列名及行号。

## 第一组：15 件展品逐件出处与算例身份

| 展品 | 真数格数 | `\TBD{}` 占位格数 | 当前真数或图形的直接出处 | `instance_id` | 判定 |
|---|---:|---:|---|---|---|
| 图1 `fig:algorithm-flow` | 无真实数据曲线；纯流程框 | 0（但图内明确写“示意/占位”“待算法定型后填”） | `docs/paper_gci_dmm_vrp_20260804/tex_draft_v2_20260819/build_approved_figures.py:276-328`；正文引用见 `sections/model_algorithm_experiments.tex:100-105` | 不适用 | 概念壳，不是算例结果 |
| 表1 `tab:parameters` | 12 | 0 | `tex_draft_v2_20260819/data/table2_model_algorithm_parameters.csv:40-51`；逐项再指向 `solver/reports/synergy_formal_20260819/joint/seed_8/metadata.json`、`data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723/tariff_carbon_hourly_calendar.csv`、`data/ChinaInstances/china81_private_rebuild_v1_20260811/vehicle_costs.csv`、`data/ChinaInstances/china81_final_suite_v2_20260815/fleet_caps.csv` | 运行元数据为 `cn-jjj-50c-01-DEPOTSEARCH-d996f755bd`；电价、车型成本等数据表本身不设实例 ID | 统一算例输入 ✅；属于组合参数源，不是一次实验结果 |
| 表2 `tab:public28` | 29（28 个“本文 Best”加 `Nbks=28`） | 243 | `tex_draft_v2_20260819/data/table4_public28.csv:2-29`；逐题源包 `solver/reports/public28_20260819/{PR11A..PR24B}_independent/` 的 `best_solution.json`、`metadata.json`、`raw_runs.csv` | PR11A--PR24B（`metadata.json` 字段名为 `instance`） | **非统一算例 ⚠️**；公开基准题，不是退役私有分支 |
| 表3 `tab:final-solution` | 32（16 个趟次号、8 个日里程、8 个固定成本）；另有 16 个真实路线序列格 | 16 | `tex_draft_v2_20260819/data/table3_physical_vehicle_schedules.csv:2-9`；`solver/reports/synergy_formal_20260819/joint/seed_8/best_solution.json#/evaluation/prepared_solution`；服务量见同目录 `raw_runs.csv:2` | `cn-jjj-50c-01-DEPOTSEARCH-d996f755bd` | 统一算例 ✅ |
| 图2 `fig:convergence` | 无真实曲线 | 0（图内文字“收敛轨迹待补”） | 当前 PDF 由 `build_approved_figures.py:331-351` 画空坐标轴和图例，没有读任何 CSV | 当前图无实例 ID | 出处不明 ❓（因为当前图没有数据） |
| 表4 `tab:carbon-charging` | 34；另有 1 个 `---` 文本格 | 20 | 时变 ASAP/碳感知及碳价扫描：`tex_draft_v2_20260819/data/table_b1_source.csv:2-3`；固定平均碳强度列是对同一充电量按日均因子重记账，说明与精确值见 `docs/paper_gci_dmm_vrp_20260804/section_5_1_draft_20260819.md:40-56,109-119`；源排班为 `solver/reports/formal_batch_20260818/carbon_sweep/0.20/asap/seed_1/best_solution.json`，实例与服务量见同目录 `raw_runs.csv:2` | `cn-jjj-50c-01-DEPOTSEARCH-d996f755bd` | 统一算例 ✅；固定平均列的一次性生成脚本未入库 |
| 图3 `fig:carbon-charging` | 有真实数据：24 小时电价/碳强度台阶、5 个样本充电窗口及事件条带、6 个碳价点 | 0 | `tex_draft_v2_20260819/data/figure3_hourly_source.csv`（24 行）、`figure3_charging_events.csv`（10 行，图中筛 5 行）、`carbon_price_scan.csv`（6 行）；读数与筛选见 `build_approved_figures.py:354-504`；排班源同表4 | 排班/充电事件为 `cn-jjj-50c-01-DEPOTSEARCH-d996f755bd`；逐时电网序列为外生区域数据 | 统一算例 ✅ |
| 表5 `tab:fleet-levels` | 26 | 22 | `solver/reports/t8_levels_20260819/cv18_ev2/best_solution.json` 与 `cv13_ev7/best_solution.json` 的 `evaluation.breakdown`、`prepared_solution`；服务量和实例见各自 `raw_runs.csv:2` | 两个成功档均为 `cn-jjj-50c-01-DEPOTSEARCH-d996f755bd` | 统一算例 ✅ |
| 图4 `fig:fleet-carbon-price` | 无燃油车/电动车实际车辆数曲线；只有一条 0.4489498211 的参考竖线 | 0（图内文字“燃油车/电动车折线数据待补”） | `build_approved_figures.py:507-527`；参考线来自图3的充电时移盈亏平衡值，不是车型派遣扫描 | 参考线源排班为 `cn-jjj-50c-01-DEPOTSEARCH-d996f755bd`；目标曲线无实例 ID | 出处不明 ❓（目标曲线不存在） |
| 表6 `tab:dynamic` | 0 | 60 | 当前无已填数字；`solver/reports/dynamic_20260819/raw_runs.csv:2-4` 三臂均为 `NOT_RUN` | 计划实例为 `cn-jjj-50c-01-DEPOTSEARCH-d996f755bd`（`metadata.json:15`），但未求解 | 统一算例计划包；无结果可判 |
| 表7 `tab:synergy` | 30 | 8 | 联合：`solver/reports/synergy_formal_20260819/joint/seed_8/best_solution.json`；单干：`standalone/ENT_A/seed_6/best_solution.json`、`standalone/ENT_B/seed_10/best_solution.json`；三者实例及服务量见各自 `raw_runs.csv:2` | 三者均为 `cn-jjj-50c-01-DEPOTSEARCH-d996f755bd` | 统一算例 ✅ |
| 图5 `fig:collaboration-fairness-routes` | 当前引用的是概念示意图，没有真实路线数据图层 | 0 | `main.tex:392-399` 引用 `figures/concept_collaboration_fairness_notitle.pdf`；交付记录称其从 `../concept_figure_20260813/concept_collaboration_fairness_notitle.pdf` 原样复制，见 `tex_draft_v2_20260819/report.md:297` | PDF 内无实例 ID | 出处不明 ❓；当前图是示意，不是退役算例结果 |
| 表8 `tab:nonlinear-charging` | 0 | 70 | 当前无已填数字；表格见 `main.tex:407-436` | 无当前结果实例 ID | 出处不明 ❓（整表无数据） |
| 表9 `tab:carbon-price` | 12 | 0 | `tex_draft_v2_20260819/data/carbon_price_scan.csv:2-7`、`table_b1_source.csv:2-3`；组装说明 `docs/handoff/reform_council_20260818/table7_figure4_data_20260819.md:29-40,69` | `cn-jjj-50c-01-DEPOTSEARCH-d996f755bd` | 统一算例 ✅ |
| 表10 `tab:allocation` | 8 | 1（分摊方法名） | `tex_draft_v2_20260819/data/table11_allocation_comparison.csv:2-4`、`table12_allocation_rules_core.csv:2-3`；底层为表7的两个单干解和联合 seed 8 解 | 均为 `cn-jjj-50c-01-DEPOTSEARCH-d996f755bd` | 统一算例 ✅ |

### 第一组的直接结论

- **没有查到一件“已填私有真数展品”来自题名所列退役分支。**
- 表2是唯一成批使用非统一实例的已填表，但它使用的是公开 PR 基准题，身份与用途在正文中明写为公开算例。
- 图5当前无法证明属于任何算例，因为它本来就是概念示意图；仓库里另有统一算例真实路线数据，但当前正文没有引用那张真实路线图。

## 第二组：占位格现在能不能从仓库填

| 展品 | 占位类别 | 仓库现状与可用字段 | 能否按当前展品口径直接填 |
|---|---|---|---|
| 图1 | 问题导向算子名称与串行链 | `build_approved_figures.py:303-306` 明写待定；机制探针有动作计数，但没有一份被当前论文批准的最终算子清单 | **不能**；缺的是算法定稿，不是 CSV 数字 |
| 表1 | 表内无占位 | 12 个数均有项目数据源；但正文 `sections/model_algorithm_experiments.tex:127` 仍有“出处或页码”占位，这不在表格单元格内 | 表内无需填；文献页码另缺 |
| 表2 | BKS、两个已发表算法的名称/Best/Avg、冻结 HGS Best/Avg、本文 Avg、Average/Nbks 汇总 | 28 个本文 Best 在 `table4_public28.csv:2-29`。全仓 `metadata.json` 扫描显示每个 PR 题只有 seed 11；PR11A/PR17A虽有多个技术包，也仍只有 seed 11。未找到文件名或内容同时提供 PR11A--PR24B BKS 的结构化参考表 | **不能直接填**。本文 Avg 无多种子；BKS 与已发表算法值仓库内确实没有；冻结 HGS 也无覆盖 28 题的同口径结果 |
| 表3 | 16 个逐趟发车/返回时刻 | `table3_physical_vehicle_schedules.csv:2-9` 的“各趟发车—返回”均为 `UNKNOWN`，并明确 `schedule=null`、`prepared_solution.routes` 无时刻字段 | **仓库内确实没有** |
| 图2 | 本文算法收敛曲线 | 候选数据 `solver/reports/synergy_formal_20260819/joint/seed_8/convergence.csv` 有 4 列、12 行，详见下一小节 | **数据能画，但不能按正文“正式收敛图”口径直接填**；该源包 `run_kind=probe`（同目录 `raw_runs.csv:2`） |
| 表4 | 固定/里程/燃油三个分项（四臂共 12 格） | 固定排班源解 `formal_batch_20260818/carbon_sweep/0.20/asap/seed_1/best_solution.json#/evaluation/breakdown` 有 `cost_fix=1780`、`cost_km=811.907161069...`、`cost_fuel=285.301637524...`；固定排班对照中四臂相同 | **有，可填 12 格**；统一算例 |
| 表4 | 电费最省臂 8 个策略相关格 | 仓库有独立优化的 `formal_batch_20260818/**/cost_min/seed_*` 探针，但它们改变了路线/排班，不是表4要求的“同一固定排班精确枚举”；当前 0.07502 扫描的 cost-min 还以 `FAILED_ABRUPT_EXIT` 收口 | **没有符合本表控制变量的数据** |
| 表4 | 四臂完成需求量 | 源排班 `formal_batch_20260818/carbon_sweep/0.20/asap/seed_1/raw_runs.csv:2` 为 `demand_served=13264.0,demand_total=13264.0`；固定、ASAP、碳感知复用同一排班 | 三个现有臂 **有**；cost-min 臂仍无同口径结果 |
| 图3 | 无占位 | 三个源 CSV 齐全，生成器还硬检查 24/10/6 行，见 `build_approved_figures.py:354-364` | 无需填 |
| 表5 | 7CV/13EV 与 2CV/18EV 两列，共 22 格 | 两包 `t8_levels_20260819/cv7_ev13/`、`cv2_ev18/` 只有失败包；`raw_runs.csv:2` 分别报未登记物理燃油车，`decision.json#/accepted=false`，没有 `best_solution.json` | **仓库内确实没有成功结果**；失败不能填成不可行 |
| 图4 | 各碳价下实际派遣 CV/EV 数量折线、全电动阈值 | 仓库只有逐车固定职责油/电成本包络 `fleet_type_envelope_20260819.md:43-108`，它报告“更优车型数”，不是重新优化后的实际派遣数 | **仓库内确实没有目标扫描数据** |
| 表6 | 15 类指标的三臂值与比较，共 60 格 | 正式包 `dynamic_20260819` 未运行。技术小试 `probe_all_mechanisms_20260818/dynamic_paired_seed11_w1/raw_runs.csv` 有 `total_cost,total_emissions_kg,customers_served,demand_served_kg,enabled_vehicles,ev_route_count,cv_route_count,charging_action_count`；`paired_results.csv` 有机械/动态成本与排放差；`per_reveal_events.csv` 有 5 批事件与充电排放 | **只有部分技术读数，不能填整表**；缺固定/里程/燃油/电费/碳成本分解、总里程、燃油与充电排放完整拆分，且正文要求的是正式批 |
| 表7 | 单干的固定/里程/燃油/电费 4 格及相对变化 4 格 | ENT_A、ENT_B 两个 `best_solution.json#/evaluation/breakdown` 可直接相加：固定 1660.000、里程 1517.483630741、燃油 386.941861569、电费 333.197084629；相对联合分别为 -18.072289%、-51.912939%、+137.539183%、-100% | **有，可填全部 8 格**；统一算例 |
| 图5 | 当前无 `\TBD`，但只是示意 | 真实节点与独立/联合路线已在 `tex_draft_v2_20260819/data/route_nodes_projected.csv`、`route_standalone_arcs_A.csv`、`route_standalone_arcs_B.csv`、`route_joint_arcs_A.csv`、`route_joint_arcs_B.csv`；底层解为表7三包 | (a)(b) **有统一算例真实路线**，但当前 PDF 未使用；(c) 的公平分配不改变路线，不能凭数据造出另一条路线 |
| 表8 | 5 种 S/R 口径下的 14 类指标，共 70 格 | 统一算例技术诊断只证明 13 次充电调用 M17 分段曲线，最高结束 SOC 45.531%，未达到 85% 拐点；见 `probe_all_mechanisms_20260818/report.md:33,133` 和 `raw_runs.csv:16` | **仓库内确实没有完整 S/R 对照**；现有诊断最多能填“13 次会话、50/50、13264/13264”这一列的局部事实，不能拼成五列比较 |
| 表9 | 表内无占位；正文另缺配对服务需求量 | `table_b1_source.csv` 的两策略复用同一源排班；源 `raw_runs.csv:2` 为 50/50、13264/13264 | 表内无需填；正文需求量 **有** |
| 表10 | 分摊方法名 | `table12_allocation_rules_core.csv:2-3` 显示两方情形下 Shapley 与核仁数值相同；但采用哪个名称是用户决定，不是数据缺口 | **不能由数据替用户填方法名** |

### 图2收敛文件专项核对

- `solver/reports/synergy_formal_20260819/joint/seed_8/convergence.csv` 列为 `cycle,wall_seconds,has_feasible,best_feasible_raw_cost`，共 **12 个数据行**（文件 `:1-13`）。第一点为 1.755506208 秒/3961.423402732485，最后一点为 604.221534374 秒/3033.205976710769。
- 横轴 **可以直接取实际运行时间（秒）**，字段就是 `wall_seconds`，无需用 cycle 或比例时间替代。
- 全仓共找到 **193** 个名为 `convergence.csv` 的文件，全部位于 `solver/reports/`。除目标文件外还有 192 个：其中 171 个在本文件或同目录元数据中直接登记统一实例；19 个位于 `formal_batch_20260818` 的中断单元，单元自身缺实例字段，但批报告 `formal_batch_20260818/report.md:7` 登记统一实例；另 2 个位于 `synergy_formal_20260819/interrupted_before_driver/standalone/ENT_A/seed_2` 与 `ENT_B/seed_2`，附近没有实例字段，故这 2 个标为 **出处不明 ❓**，不猜。
- 193 个文件按一级报告目录分布：`formal_batch_20260818` 110、`synergy_formal_20260819` 33、`speedup_trial_20260819` 13、`ablation_20260819` 9、`station_prune_20260819` 8、`calibration_20260818` 5、`probe_all_mechanisms_20260818` 4、`two_knives_20260818` 3，其余 8 个目录各 1--2 个。

### 图4与四个历史阈值专项核对

- 仓库没有“不同碳价下重新优化后实际派遣燃油车/电动车数量”的扫描表。
- `0.296271`、`1.705754`、`1.969218` 在 `docs/handoff/reform_council_20260818/fleet_type_envelope_20260819.md:89-99`，是固定 9 个物理车辆日职责逐车换型的正碳价成本交点；源解为 `formal_batch_20260818/carbon_sweep/0.20/asap/seed_1/best_solution.json`，统一算例。
- `0.446009` 不在车型包络中；它在 `table7_figure4_data_20260819.md:40`，是“全局最高排放充电组合 vs 最低排放充电组合”的充电时移阈值。论文图3/图4当前引用的 `0.4489498210731408` 则是“ASAP 当前排程 vs 最低排放组合”的另一阈值。四个数字不能合称为“四个车型翻转碳价”。
- 包络文件 `:101-108` 的 3/5/1、2/6/1、0/8/1 是“油车更优/电车更优/未知的固定职责数”，不是实际派遣车辆数，不能直接画进图4。

### 表2公开算例专项核对

- 28 个“本文 Best”来自 `solver/reports/public28_20260819/` 下 28 个 `*_independent` 目录，汇总到 `tex_draft_v2_20260819/data/table4_public28.csv:2-29`。
- 每题当前只有 seed 11；全仓其他同题技术包也没有第二个种子。因此没有能填本文 Avg 的多种子结果。
- 未找到覆盖 PR11A--PR24B 的 BKS 参考值文件；现有 CSV 的“公开最好值及版本”列逐行都是 `待补(BKS)`。
- `solver/reports/public_28_20260819/`（名字中有下划线）是 PR17A/PR24A 等校准材料，不是 28 题多种子正式批。

### 表6动态需求专项核对

- `data/ChinaInstances/china81_dynamic_stream_v1_20260811/metadata.json:3` 的 `base_instance_id` 是 `cn-prd-50c-01-V3-TWO-SHIFT-GZ-FS`；`:6` 明写 `formal_experiment=false`。它是珠三角旧 `V3-TWO-SHIFT-GZ-FS` 分支，**不是**统一算例。
- 统一算例上确有技术小试 `solver/reports/probe_all_mechanisms_20260818/dynamic_paired_seed11_w1/`：`metadata.json:20` 是统一 ID，`raw_runs.csv:2-4` 有三臂技术读数；报告 `:37` 明写这些小预算接线结果不支持性能结论。
- 当前拟用于正文正式口径的 `solver/reports/dynamic_20260819/` 也是统一 ID，但 `metadata.json:5,9` 为 `HALT_PRE_SOLVE_CONTRACT_MISMATCH`、`solver_entered=false`，`raw_runs.csv:2-4` 全部 `NOT_RUN`。因此统一算例上 **没有正式动态实验结果**。
- 在 `data/ChinaInstances/` 下没有找到以统一实例 ID 为 `base_instance_id` 的持久化动态订单流目录；统一技术小试的事件流记录在报告包内，不等于旧 `china81_dynamic_stream_v1_20260811`。

## 第三组：统一算例的规模事实

| 项目 | 直接读数 | 证据 |
|---|---:|---|
| 客户数 | 50 | `.../cn-jjj-50c-01-DEPOTSEARCH-d996f755bd/nodes.csv:101-150`，`node_type=customer` |
| 车场数 | 2 | 同文件 `:2-3`，`node_type=depot` |
| 公共充电站节点数 | 97 | 同文件 `:4-100`，`node_type=station` |
| 车场 A 的活动燃油车/电动车上限 | 3 / 3 | `china81_final_suite_v2_20260815/fleet_caps.csv:174` 的 `base_all_cv_routes_Rd,base_all_ev_routes_Re`；运行元数据 `synergy_formal_20260819/joint/seed_8/metadata.json#/fleet_caps_by_depot/D_OSM_WAY_1003511503` 也为 3/3 |
| 车场 B 的活动燃油车/电动车上限 | 7 / 7 | `fleet_caps.csv:175` 与运行元数据同字段，均为 7/7 |
| 企业归属文件 | 存在，共 50 行 | `.../enterprise_assignment.csv:2-51` |
| 企业 A | C001--C025，共 25 个，绑定 `way/1003511503` | `enterprise_assignment.csv:2-26` |
| 企业 B | C026--C050，共 25 个，绑定 `way/1071205721` | `enterprise_assignment.csv:27-51` |

需要特别说明 `fleet_caps.csv:174-175` 同时还保存了 `num_cv,num_ev=4/2、9/5`。该文件把它们标为 `ENDOGENOUS_NOT_FIXED` 的构成字段；实际运行元数据消费的 `fleet_caps_by_depot` 是 3/3、7/7。因此本文若写“上限”，当前可复现运行口径应取 **3/3、7/7**，不能取 4/2、9/5。

论文句子：

> 代表实例为京津冀50客户、2车场、97个公共站节点的构造算例，客户责任按编号等分为两家企业各25个。

**核对结果：这句话正确。** 50、2、97、25/25 均与上表直接文件计数一致。证据位置为 `sections/model_algorithm_experiments.tex:125` 及上述 `nodes.csv`、`enterprise_assignment.csv`。

## 第四组：81 例套件现状

### 实际目录数与区域—规模分布

`data/ChinaInstances/china81_final_suite_v2_20260815/metadata.json:3` 登记 `instance_count=82`；对 `instances/` 下实际子目录计数也是 **82**。

| 区域 | 10c | 15c | 20c | 25c | 50c | 75c | 100c | 150c | 200c | 合计 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| jjj 京津冀 | 3 | 3 | 3 | 3 | **4** | 3 | 3 | 3 | 3 | 28 |
| prd 珠三角 | 3 | 3 | 3 | 3 | 3 | 3 | 3 | 3 | 3 | 27 |
| cy 成渝 | 3 | 3 | 3 | 3 | 3 | 3 | 3 | 3 | 3 | 27 |
| 合计 | 9 | 9 | 9 | 9 | 10 | 9 | 9 | 9 | 9 | **82** |

多出来的一项在 jjj 50c：`cn-jjj-50c-01-DEPOTSEARCH-d996f755bd`。

### 旧分支标记

| 标记 | 目录数 | 关系 |
|---|---:|---|
| `DEPOTSWAP` | 0 | 无 |
| `METRO` | 18 | 全部同时含 `V3-TWO-SHIFT` |
| `PRDFIX` | 4 | 全部同时含 `V3-TWO-SHIFT` |
| `FS` | 7 | 全部同时含 `V3-TWO-SHIFT` |
| `V3-TWO-SHIFT` | 52 | 由 METRO 18、PRDFIX 4、FS 7、DP 23 组成 |

具体目录如下；DP 组虽不含题目列出的后三个后缀，但列出它是为了把 52 个 `V3-TWO-SHIFT` 目录完整枚举。

<details><summary>METRO：18 个</summary>

`cn-cy-100c-01-V3-TWO-SHIFT-METRO`；`cn-cy-100c-02-V3-TWO-SHIFT-METRO`；`cn-cy-150c-01-V3-TWO-SHIFT-METRO`；`cn-cy-150c-02-V3-TWO-SHIFT-METRO`；`cn-cy-150c-03-V3-TWO-SHIFT-METRO`；`cn-cy-200c-01-V3-TWO-SHIFT-METRO`；`cn-cy-200c-02-V3-TWO-SHIFT-METRO`；`cn-cy-200c-03-V3-TWO-SHIFT-METRO`；`cn-cy-20c-01-V3-TWO-SHIFT-METRO`；`cn-cy-20c-02-V3-TWO-SHIFT-METRO`；`cn-cy-25c-01-V3-TWO-SHIFT-METRO`；`cn-cy-25c-03-V3-TWO-SHIFT-METRO`；`cn-cy-50c-01-V3-TWO-SHIFT-METRO`；`cn-cy-75c-01-V3-TWO-SHIFT-METRO`；`cn-cy-75c-03-V3-TWO-SHIFT-METRO`；`cn-jjj-15c-01-V3-TWO-SHIFT-METRO`；`cn-jjj-15c-03-V3-TWO-SHIFT-METRO`；`cn-prd-200c-03-V3-TWO-SHIFT-METRO`

</details>

<details><summary>FS：7 个</summary>

`cn-jjj-75c-02-V3-TWO-SHIFT-FS`；`cn-prd-100c-02-V3-TWO-SHIFT-FS`；`cn-prd-150c-01-V3-TWO-SHIFT-FS`；`cn-prd-150c-03-V3-TWO-SHIFT-FS`；`cn-prd-200c-02-V3-TWO-SHIFT-FS`；`cn-prd-20c-02-V3-TWO-SHIFT-FS`；`cn-prd-25c-02-V3-TWO-SHIFT-FS`

</details>

<details><summary>PRDFIX：4 个</summary>

`cn-prd-100c-03-V3-TWO-SHIFT-PRDFIX`；`cn-prd-150c-02-V3-TWO-SHIFT-PRDFIX`；`cn-prd-200c-01-V3-TWO-SHIFT-PRDFIX`；`cn-prd-75c-02-V3-TWO-SHIFT-PRDFIX`

</details>

<details><summary>其余 V3-TWO-SHIFT-DP：23 个</summary>

`cn-cy-100c-03-V3-TWO-SHIFT-DP`；`cn-cy-10c-01-V3-TWO-SHIFT-DP`；`cn-cy-15c-01-V3-TWO-SHIFT-DP`；`cn-cy-15c-02-V3-TWO-SHIFT-DP`；`cn-cy-25c-02-V3-TWO-SHIFT-DP`；`cn-cy-50c-02-V3-TWO-SHIFT-DP`；`cn-cy-50c-03-V3-TWO-SHIFT-DP`；`cn-cy-75c-02-V3-TWO-SHIFT-DP`；`cn-jjj-100c-01-V3-TWO-SHIFT-DP`；`cn-jjj-100c-02-V3-TWO-SHIFT-DP`；`cn-jjj-100c-03-V3-TWO-SHIFT-DP`；`cn-jjj-150c-01-V3-TWO-SHIFT-DP`；`cn-jjj-150c-02-V3-TWO-SHIFT-DP`；`cn-jjj-150c-03-V3-TWO-SHIFT-DP`；`cn-jjj-200c-01-V3-TWO-SHIFT-DP`；`cn-jjj-200c-02-V3-TWO-SHIFT-DP`；`cn-jjj-200c-03-V3-TWO-SHIFT-DP`；`cn-jjj-20c-03-V3-TWO-SHIFT-DP`；`cn-jjj-25c-03-V3-TWO-SHIFT-DP`；`cn-jjj-50c-02-V3-TWO-SHIFT-DP`；`cn-jjj-50c-03-V3-TWO-SHIFT-DP`；`cn-jjj-75c-01-V3-TWO-SHIFT-DP`；`cn-jjj-75c-03-V3-TWO-SHIFT-DP`

</details>

## 第五组：正文中对算例身份、区域、规模和车场的表述

先给全文检索结论：`main.tex` 与 `sections/*.tex` **没有出现任何完整算例 ID、`way/1003511503`、`way/1071205721`、`GZ-FS`、`PRDFIX`、`METRO`、`DEPOTSWAP` 或 `V3-TWO-SHIFT` 字样**。正文只用“代表实例”“本算例”“同一实例”承接具体身份；唯一把区域和规模说全的是分节文件第 125 行。

下表列出所有会让读者判断“这是哪个算例/多大规模/哪个区域”的正文句子；纯模型定义（如“系统包含车场集合”）不具有具体算例身份，另列在表后。

| 位置 | 原文 | 核对 |
|---|---|---|
| `main.tex:120` | “在同一代表实例和同一排放核算下，分别观察充电时刻、车型指派和动态发车三个决策层” | **无法单凭本句核实身份**；依赖分节文件第 125 行。充电与车型现有源均统一；动态正式结果尚无 |
| `sections/model_algorithm_experiments.tex:125` | “代表实例为京津冀50客户、2车场、97个公共站节点的构造算例，客户责任按编号等分为两家企业各25个。动态事件流包含10个新增客户事件……共5个触发批……” | 规模与归属 **一致 ✅**；技术动态包确有 10 个新增事件/5 批，但没有以统一实例为 base 的持久化正式事件流目录，故动态事件部分只能核到技术包，不能核到正式数据集 |
| `main.tex:141` | “公开实验采用28个多车场带时间窗算例……当前每题只有一次运行……” | **一致 ✅**；`public28_20260819` 恰有 28 题，每题仅 seed 11。这里明确不是统一私有算例 |
| `main.tex:193` | “表3……逐趟客户序列已由保存解登记；发车/返回时刻没有原始字段……” | **一致 ✅**；统一 seed 8 解，排班 CSV 的时刻字段均为 UNKNOWN |
| `main.tex:226` | “该保存解完成50/50个客户和13264/13264 kg需求，使用8辆实体车执行16趟……” | **一致 ✅**；`synergy_formal_20260819/joint/seed_8/raw_runs.csv:2` 与 `best_solution.json` |
| `main.tex:234` | “现有72个过程点来自未通过整包验收的首批配置……图2只保留……私有算例……” | “私有算例”未写 ID；现有候选 `joint/seed_8/convergence.csv` 是统一实例但只有 12 点。**72 点的精确源文件在当前稿中未登记，无法核实该数字** |
| `main.tex:247` | “四个对照臂使用同一实例与服务要求……已有三臂完成50/50个客户……” | 现有三个固定排班臂可追到统一实例 **一致 ✅**；第四个 cost-min 同口径数据不存在 |
| `main.tex:284` | “该格只选取B场4辆电动车作样本……已登记的10次充电中有9次改期成功……” | **一致 ✅**；`figure3_charging_events.csv` 10 行，生成器筛出 B 场 4 车的 5 个当日事件；源排班统一实例 |
| `main.tex:288` | “车型层登记18CV/2EV、13CV/7EV、7CV/13EV和2CV/18EV四个可用名额档。前两档……50/50、13264/13264……” | **一致 ✅**；四包均计划统一实例，前两包有解，后两包是运行错误 |
| `main.tex:324` | “本算例已测得的0.449元/kg只作为‘见图3’的淡参考线……” | 算例身份 **一致 ✅**；但 0.449 是充电时移阈值，不是车型派遣阈值，正文已用“见图3”区分 |
| `main.tex:328` | “现有动态结果包未通过验收且求解器没有进入……” | **一致 ✅**；`dynamic_20260819/metadata.json:5,9` |
| `main.tex:362` | “两臂均完成50/50个客户和13264/13264 kg需求，使用8辆实体车执行16趟……” | **一致 ✅**；统一实例的两个单干解合计与联合解 |
| `main.tex:405` | “当前没有完整S/R正式对照……表8全部留白” | **一致 ✅**；只有统一实例技术诊断，没有正式五列对照 |
| `main.tex:440` | “两策略的完成客户数和完成需求量沿用充电时刻层的同批服务要求……” | **一致 ✅**；统一源排班 50/50、13264/13264 |
| `main.tex:465` | “它固定同一联合方案……只改变3033.206元联合总成本在两家企业之间的承担额” | **一致 ✅**；统一 joint seed 8 与分摊 CSV |

正文中还有一般性车场/客户表述：`main.tex:109,115,117,119,131,133,135,360,488` 和 `sections/model_algorithm_experiments.tex:15,49,72,77,79,109,115,123,127`。这些句子描述模型、研究背景或参数来源，没有区域、规模、算例 ID 或具体车场身份，不能据此判断是否引用了退役算例。

## 第六组：仍未查清或证据不闭合的项目

1. **图2正文所说“72 个过程点”的精确文件没有登记。** 当前最清楚的统一实例候选只有 seed 8 的 12 行 `convergence.csv`；另有 193 份同名文件，不能凭数量猜哪几份组成 72 点。
2. **193 份收敛文件中有 2 份中断文件无法从附近文件确认实例 ID。** 路径为 `synergy_formal_20260819/interrupted_before_driver/standalone/ENT_A/seed_2/convergence.csv` 与 ENT_B 同路径。
3. **表2的 BKS、两种已发表算法逐题值、冻结 HGS 全 28 题值和多种子均值均未找到。** 搜索范围包括 `data/`、`solver/`、`docs/` 中含 `BKS`、`best known`、`benchmark`、PR11A--PR24B 的 CSV/JSON/Markdown/文本文件。
4. **表3逐趟时间不存在于保存解。** 不是尚未抄入论文，而是源字段 `schedule=null`。
5. **表4固定平均碳强度列的一次性生成脚本未入库。** 数值、算式和统一源解均能追到，但无法执行原脚本逐字节复现；证据见 `section_5_1_draft_20260819.md:109-119`。
6. **用户点名的 `solver/reports/time_carbon_3arms_20260817/` 当前不存在。** 当前可见的三臂/充电数据实际落在 `formal_batch_20260818` 与 `docs/handoff/reform_council_20260818/table7_figure4_data_20260819.md`。
7. **图4没有实际派遣扫描。** 三个车型正交点和一个充电阈值都找到了，但比较对象不同，不能拼成车辆数曲线；全电动实际派遣阈值也没有。
8. **统一实例正式动态实验没有结果。** 旧持久化动态流绑定退役 PRD/GZ-FS 算例；统一实例只有技术小试和一个求解前停止的正式计划包。
9. **表8没有完整 S/R 对照。** 现有 13 次非线性曲线调用未进入 85% SOC 非线性段，不能生成表中五列比较。
10. **图5当前概念 PDF 没有机器可读实例身份。** 仓库另有统一实例真实路线 CSV，但正文并未引用它；公平分摊又不改变路线，第三格的“转归解”没有独立路线数据可核。
11. **车队文件同时保留两组构成字段。** 可复现运行采用 `base_all_cv_routes_Rd/base_all_ev_routes_Re=3/3、7/7`；同两行的 `num_cv/num_ev=4/2、9/5` 不应被误读成活动上限。文件本身没有一段就地说明两组字段的语义差别，只能由运行元数据确认实际消费值。
12. **“81 例套件”与实际 82 目录不一致。** 这是名称与内容数量不一致，不是计数误差；元数据自己也写 82。

## 搜索覆盖范围

- 论文：`docs/paper_gci_dmm_vrp_20260804/tex_draft_v2_20260819/main.tex`、`sections/*.tex`、`data/*.csv`、`report.md`、`build_approved_figures.py`。
- 2026-08-15 之后重点报告：`solver/reports/public28_20260819/`、`public_28_20260819/`、`synergy_formal_20260819/`、`t8_levels_20260819/`、`dynamic_20260819/`、`ablation_20260819/`、`speedup_trial_20260819/`、`station_prune_20260819/`、`t6_t8_20260819/`。
- 题目点名及相关历史报告：`solver/reports/formal_batch_20260818/`、`probe_all_mechanisms_20260818/`；点名的 `time_carbon_3arms_20260817/` 未检索到。
- 数据：`data/ChinaInstances/china81_final_suite_v2_20260815/`、`china81_dynamic_stream_v1_20260811/`、`china81_runtime_parameter_authority_v4_20260723/`、`china81_private_rebuild_v1_20260811/`。
