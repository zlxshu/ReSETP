# 车辆数量硬上限与多车场车队设定证据记录

日期: 2026-06-26

## 一句话结论

本轮按用户决策只在代码侧试行车辆数量硬上限: 代码现在会从生成实例 metadata 或原始 EVRPTW-MF 文本中的 `num_cv/num_ev`、`numPetrolVeh/numElectroVeh` 读取上限，并由 `check_solution()` 判定超限为 `FLEET_SIZE` 违规。

这不是改碳价、电池、速度或成本项，但它确实改变了此前 solver 的可行性语义: 之前超过 metadata 车辆数不会被判 infeasible；现在会被判 infeasible。注意: 用户随后明确要求不得改论文建模，因此本轮新增到 TeX 的车辆数量公式和参数表解释已撤回，论文模型文本保持原状。

## 本项目当前采用的规则

当前采用的是“系统层面的类型车辆硬上限”:

- `num_cv` / `m^g`: 当前阶段最多可启用的燃油车路线数。
- `num_ev` / `m^e`: 当前阶段最多可启用的电动车路线数。
- 多车场实例暂不自动把车辆数按车场数量翻倍。
- 车场维度的车辆分配仍由 route 的 `home_depot_id` 和现有流/回场约束决定；本轮没有新增 per-depot vehicle cap，例如 `m_d^g/m_d^e`。

这样做的原因很简单: 文献里多车场车辆数设定并没有唯一规则。直接把单车场车辆数按车场数翻倍，是一个新的场景假设，不是可以默认推出的事实。

## 文献和本地证据

### Goeke/Schneider mixed fleet

本项目原始 E-UK/Goeke 数据带有 `numVeh/numPetrolVeh/numElectroVeh` 字段。早期对齐记录中，E-UK25 为 `numVeh=3, numPetrolVeh=2, numElectroVeh=1`，E-UK50 为 `numVeh=7, numPetrolVeh=4, numElectroVeh=3`。这说明原算例确实记录了车辆数量上限，不只是成本参数。

本地证据:

- `/Volumes/移动硬盘（512G）/paper_input/SETP-template-20230830/research_materials/instance_data_alignment_20260531.md:49-50`
- `/Volumes/移动硬盘（512G）/ReSETP/docs/handoff/codex_prompts/08_e2_instance_generation.md`

Goeke/Schneider 论文文本还明确提到最大使用车辆数要符合 fleet composition；这支持把车辆类型数量作为约束理解。

本地证据:

- `/Volumes/移动硬盘（512G）/paper_input/SETP-template-20230830/research_materials/pdf_text_extracts/Goeke和Schneider___2015___Routing_a_mixed_fleet_of_electric_and_conventional_vehicles.txt:407-410`

同时要保留边界: Goeke/Schneider 也引用了 fleet-size-and-mix 分支，其中有“unlimited number of ECVs”这类设定。这说明 VRP 文献里存在两种不同建模口径: 固定可用车队上限，或让车队规模/车型组成由固定费和优化决定。我们当前选择的是前者。

本地证据:

- `/Volumes/移动硬盘（512G）/paper_input/SETP-template-20230830/research_materials/pdf_text_extracts/Goeke和Schneider___2015___Routing_a_mixed_fleet_of_electric_and_conventional_vehicles.txt:125-128`

### Soriano et al. 2023 multi-depot profit fairness

Soriano 的多车场收益公平问题把每个 depot、每个 period/day 可用车辆集合写成 `K_dh`，并且 route 数最多为 `|K_dh|`。这支持“多车场里车辆可以按车场/伙伴设可用上限”的建模方式。

本地证据:

- `/Volumes/移动硬盘（512G）/paper_input/SETP-template-20230830/research_materials/pdf_text_extracts/Soriano_等___2023___The_multi_depot_vehicle_routing_problem_with_profit_fairness.txt:232-242`

他们还专门讨论过限制每个 partner 可用车辆数，以避免 workload shifts。这说明在多车场协作里，“每个伙伴/车场拥有有限车辆”是合理机制，不是牵强补丁。

本地证据:

- `/Volumes/移动硬盘（512G）/paper_input/SETP-template-20230830/research_materials/pdf_text_extracts/Soriano_等___2023___The_multi_depot_vehicle_routing_problem_with_profit_fairness.txt:623-631`

但这也说明，如果未来要做 per-depot cap，应该明确写成 `m_d^g/m_d^e` 或 `K_dh` 这种结构；不能把当前总量 `m^g/m^e` 偷换成“每个车场各有一份”。

### Wang et al. 2023 collaborative multidepot EVRP

Wang 的协同多车场 EVRP 强调客户服务共享、共享充电站和多车场协作，并把“使用多少 EV”作为优化目标之一。文中例子显示优化后 EV 数从 10 降到 7、从 29 降到 13。

本地证据:

- `/Volumes/移动硬盘（512G）/paper_input/SETP-template-20230830/research_materials/pdf_text_extracts/Wang_等___2023___Collaborative_multidepot_electric_vehicle_routing_problem_with_time_windows_and_shared_charging_stat.txt:40-44`
- `/Volumes/移动硬盘（512G）/paper_input/SETP-template-20230830/research_materials/pdf_text_extracts/Wang_等___2023___Collaborative_multidepot_electric_vehicle_routing_problem_with_time_windows_and_shared_charging_stat.txt:297-308`
- `/Volumes/移动硬盘（512G）/paper_input/SETP-template-20230830/research_materials/pdf_text_extracts/Wang_等___2023___Collaborative_multidepot_electric_vehicle_routing_problem_with_time_windows_and_shared_charging_stat.txt:327-331`
- `/Volumes/移动硬盘（512G）/paper_input/SETP-template-20230830/research_materials/pdf_text_extracts/Wang_等___2023___Collaborative_multidepot_electric_vehicle_routing_problem_with_time_windows_and_shared_charging_stat.txt:1390-1398`

这类文献支持“车辆数量是重要运营资源”，但不支持直接把每个车场的 EV 数按 depot 数复制。它更像是共享资源优化，而不是简单扩容。

### Fleet-size-and-mix 多车场文献

Zotero 索引里有 `Alternative formulations and improved bounds for the multi-depot fleet size and mix vehicle routing problem` 以及 `Time-dependent fleet size and mix multi-depot vehicle routing problem`。这类文献的核心是“车辆类型和数量本身可优化”，与我们当前“给定车辆类型数量硬上限”的口径不同。

本地索引:

- `/Volumes/移动硬盘（512G）/paper_input/SETP-template-20230830/research_materials/zotero_vrp_material_candidates_20260531.csv:148`
- `/Volumes/移动硬盘（512G）/paper_input/SETP-template-20230830/research_materials/zotero_vrp_material_candidates_20260531.csv:258-260`

因此不能用 fleet-size-and-mix 文献去证明“我们已有模型可以无限买 EV”。如果论文想走这条路，需要把模型改成 fleet-size-and-mix，并重新解释固定成本、车辆购买/租赁数量、资本预算和上限。这不是本轮采用的设计。

### 充电容量补充证据

Froger et al. 2022 明确指出许多 EVRP 研究隐含假设充电站可同时服务无限车辆，而现实中每个充电站通常只有固定且较少的充电器。这支持后续继续查“车场充电桩容量/充电资本预算”，但这不是本轮车辆数硬上限改动的一部分。

本地证据:

- `/Volumes/移动硬盘（512G）/paper_input/SETP-template-20230830/research_materials/pdf_text_extracts/Froger_等___2022___The_electric_vehicle_routing_problem_with_capacitated_charging_stations.txt:51-54`
- `/Volumes/移动硬盘（512G）/paper_input/SETP-template-20230830/research_materials/pdf_text_extracts/Froger_等___2022___The_electric_vehicle_routing_problem_with_capacitated_charging_stations.txt:108-112`

## 对当前代码的含义

当前最克制、最容易解释的版本是:

1. 代码中 `num_cv/num_ev` 已穿透到 `Instance`，由 checker 判硬违规。
2. 生成多车场实例时，不默认按车场数翻倍车辆。若未来需要 per-depot 车辆上限，必须先经用户同意并显式建模，不能由代码默默推导。
3. 旧 09q/09n 诊断中所有“无限 EV”结论都要重新理解: 它们说明旧实现放松了 fleet cap；现在硬上限试行后，正式 E2/T3 必须重新跑或先做 feasibility gate。

## 后续必须先验收的风险

硬上限恢复后，不能立刻进入正式 E2/T3。需要先做一个很小的 feasibility gate:

- 对 10-200 全规模代表实例，检查默认 `num_cv/num_ev` 下能否构造零违约 warm start。
- 如果大量 `INIT_INFEASIBLE`，说明当前 route=vehicle 的实现与原始 `numVeh` 口径不兼容；那时不能硬写“车辆上限解决故事”，必须回到车辆复用/车次语义或 per-depot 场景设计。
- 如果可行，再看 280kWh 或来源电池候选在硬上限下是否自然落入 20%-80% 混合带。

这一步的验收标准应该是可行性先过，再谈成本和混合比例。

本轮实现后做过一个临时 warm-start 探针: E2 `vanilla/multidepot` 的 10/15/20/25/50/75/100/150/200c `-01` 与 `threeshift` 的 50/75/100/150/200c `-01`，在当前 metadata `num_cv/num_ev` 和共同 warm-start 构造下均报 `Initial solution is infeasible`。这不是严格数学证明不可行，因为它只测试了当前构造器；但它足以说明，恢复 hard cap 后不能直接沿用旧 E2/T3 运行链，必须先专门处理 hard-cap feasibility。
