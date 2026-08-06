# R2：论文重构数据证据盘点

状态：`R2_EVIDENCE_INVENTORY_COMPLETE`

## 结论

现有数据不能整篇直接搬用。4.2 的公开算例结果可直接使用，但 China81 五算法表使用旧车型且比较协议不等算力，当前算法的组件消融也没有；5.1 的固定路线充电择时数据完整，可直接支撑“只改变充电开始时刻”的时变碳强度效应，联合优化结果只能支撑三项 50 客户算例上的有限响应；5.2 没有按预设电动车占比档位运行的当前 China81 正式结果；5.3 只有低成本试验、失败机理和零搜索时机体检，没有正式效果实验。4.1 的 44 项来源台账可直接作为来源底账，但 12 处措辞落差尚未消化，且 5 类参数来源仍未登记，因此不足以直接形成完整的 4.1。

必须重新运行搜索的项目共四项：当前车型下的 China81 五算法同协议比较、当前算法的一因素组件消融、当前 China81 的电动车占比分档敏感性、动态需求触发正式效果。其余缺口要么已有完整结果，要么只需读取和机械汇总现有文件，要么属于来源证据完全缺失。

## 4.1 算例与参数台账

| 需要什么数据 | 仓库里有没有 | 路径 | 判定 | 判定理由 |
|---|---|---|---|---|
| China81 输入来源逐项台账 | 有 | `docs/handoff/diagnosis_20260802/d4_instances/provenance_ledger.json`；同目录 `report.md` | 直接可用 | `provenance_ledger.json` 长度为 44；`report.md:7` 给出构造 26、公开发布 9、文献迁移 4、未登记 5、观测 0，`:21-68` 逐项列出 P01--P44。可直接写来源类别和证据边界。 |
| 可直接落入 4.1 的统一算例说明与数值参数表 | 没有成品；底层数据有 | `docs/handoff/diagnosis_20260802/d4_instances/report.md`、`wording_gaps.json`，以及报告 `:72-74` 所列五套分散权威包 | 需重算但不需重新搜索 | `done.json` 为 `provenance_items=44, wording_gaps=12`；`report.md:72` 明确现有 lineage 只登记 L-main，China81 要拼接位置、订单、设施、道路、运行参数和车队五套包；`:91-117` 列出 12 处需要按现有字段重做的表述。机械抽取和勾稽即可，不需要求解搜索。 |
| 公共充电服务费 0.40 元/kWh 的可回放来源 | 没有 | `docs/handoff/diagnosis_20260802/d4_instances/report.md:45`；`provenance_ledger.json` P21 | 完全没有 | P21 分类为“未登记”；运行日历只给 `service_fee_class=UNIFORM_SCENARIO_PROXY_NOT_MARKET_OBSERVATION`，没有命名市场或合同来源。 |
| 迎风面积投影因子 0.85 与空气阻力系数 0.45 的可回放来源 | 没有 | `docs/handoff/diagnosis_20260802/d4_instances/report.md:52-53`；`provenance_ledger.json` P28、P29 | 完全没有 | P28、P29 均为“未登记”；`wording_gaps.json:28-35` 还指出正文 6.08 m² 与当前代码 4.6376 m² 冲突，不能把实现值写成已有文献来源。 |
| EV 初始 SOC=0 的观测或文献来源 | 没有 | `docs/handoff/diagnosis_20260802/d4_instances/provenance_ledger.json:275-279`；`report.md:55` | 完全没有 | 只有 `china81.py:893-895` 的 `initial_ev_battery_kwh=0.0` 实现值，台账注明“未找到命名车队班前 SOC 或独立来源合同”。 |
| NL90 分段充电曲线的车型实测或具页码来源 | 没有 | `docs/handoff/diagnosis_20260802/d4_instances/provenance_ledger.json:281-288`；`report.md:56` | 完全没有 | 代码和正文能对上“90% 前额定、90%--100% 半功率”，但台账分类为“未登记”，没有映射到 ES1 77.28 kWh 车型实测曲线或具页码文献。 |

判定：D4 足以直接写 4.1 的“来源边界”，不足以直接写完整 4.1。缺的是统一数值表、对 12 处运行时错配的机械回填，以及上述 5 类未登记参数中的来源证据；前两类不需要搜索，后一类当前仓库完全没有。

## 4.2 算法有效性台账

| 需要什么数据 | 仓库里有没有 | 路径 | 判定 | 判定理由 |
|---|---|---|---|---|
| 公开 28 算例的算法质量、重复与停止数据 | 有 | `baselines/e2_final_campaign_20260720/mv_hgs_sp_final/p1_formal_gate/` | 直接可用 | `decision.json:3-15` 为 28/28、280 个种子单元、264 胜/16 平/0 负，MV-HGS-SP 的 `hybrid_error_pct=0.9048706160882664`；`metadata.json:5-26` 为种子 1--10 及 `K_MOTHER=4000, CAP_MOTHER=240s, K_EPOCH=2000, CAP_EPOCH=60s, MAX_EPOCHS=4, STALL_EPOCHS=2, SP_TIME=10s`；`raw_runs.csv` 为 280 行数据。 |
| 当前车型下的 China81 五算法同协议比较 | 有旧结果，没有当前车型结果 | `baselines/algorithm_prototypes/china81_vs_opensource_20260727/` | 必须重跑搜索 | `decision.json` 有 2025/2025 行、405 配对、354/46/5 和平均改善 1.919118%；但其 `protocol_disclosure` 明列 O 为新跑 `NoImprovement(3000)`，F/E/M/MV 为封存固定迭代，`archive_wallclock_available=false`、不可声称同批同机。`README.md:20-23` 给出同一边界。`docs/handoff/e2_e7_decision_source_execution_audit_20260801.md:52-54` 核实五臂锁定旧车型 140.41 kWh/1000 kg/3300 kg/6.0775 m²，而当前为 77.28 kWh/1700 kg/2600 kg/4.6376 m²；旧内部比较有效，但不能改称当前车型结果。 |
| 当前 MV-HGS-SP 的一因素组件消融表 | 没有；只有旧 ALNS 组件表 | `baselines/e2_alns/e2b_component_ablation_formal_20260715/` | 必须重跑搜索 | 旧包确有 `E2B_FORMAL_EVIDENCE_READY`，9 个 L-main-threeshift 算例×5 种子×4 臂，`decision.json` 为 45 个比较单元、180 行；A/B/C 各 4000 次搜索，D 为复用 C 路线的 0 搜索充电择时（`report.md:3-9`）。它隔离的是连续/分阶段/跨场/充电择时，既不是 China81 当前车型，也不是当前 MV-HGS-SP 部件的一因素表，不能直接承担新版 4.2 的组件归因。 |

## 5.1 时变碳强度台账

| 需要什么数据 | 仓库里有没有 | 路径 | 判定 | 判定理由 |
|---|---|---|---|---|
| 固定路线、车型、充电量下的 ASAP--CARBON 充电择时全量结果 | 有 | `baselines/china_e3_e7/e4_carbon_timing_20260729/` | 直接可用 | `decision.json` 为 `PASS_COMPLETE_ZERO_SEARCH_REPLAY`、`observed_pair_rows=expected_pair_rows=11340`、`search_candidate_count=0`；`report.md:64-70` 为 22680 次两臂复算、两臂违约均 0，唯一变化量为 `charge_start_second`，且预测碳强度等于核算碳强度。它直接支撑“冻结路径与车型后，时变碳强度驱动充电时刻迁移”的效应；不支撑路线/车型联动，也不支撑预测误差。 |
| 固定路线结果的正文表和机制图数据 | 有 | `docs/paper_v2/figures_e4_20260731/` | 直接可用 | `validation_summary.json.checks.metric_values` 给出充电排放 −54.970371998766%、系统排放 −9.746262546543%、充电电费 +134.879776719245%、完整模型成本 +1.845374763870%；`report.md:47-54` 给出绝对总量和共同分母 `405×28=11340`，`:13-17` 验证原始行数、哈希、空值和勾稽。 |
| 路线—车型—充电联合优化的配对结果 | 有 | `baselines/china_e3_e7/e4_joint_routing_20260801/formal_panel_20260801/` | 直接可用 | `decision.json` 为 90 行、30 个三目标配对且全 PASS。成本加碳相对纯成本：系统排放 −2.679143%、运营成本 +0.0000448%、路线/车型改变 2/30；纯排放相对纯成本：−13.935353%、+2.486564%、改变 19/30（`report.md:5-10`）。它能支撑“三个 50c 算例、单趟口径下联合目标响应有限且目标依赖”；不能支撑一般性的“含碳目标会改变路线或车型”，也没有跨规模/跨地区面板。 |

## 5.2 车队电动化配置台账

| 需要什么数据 | 仓库里有没有 | 路径 | 判定 | 判定理由 |
|---|---|---|---|---|
| 当前 China81 车队容量构造及三个 rho 档 | 有 | `baselines/china_e3_e7/e3e6_gates_01_20260729/gate1_d2a/fleet_caps.csv` | 直接可用 | CSV `:1-8` 可见 `base_all_cv_routes_Rd, main_reserve_factor, num_cv, num_ev, sensitivity_json`。`run_e3e6_gates_01_20260729.py:324-334` 定义每档始终 `num_cv=R_d`，`num_ev=max(1,ceil((rho-1)R_d))`；`report.md:3-7` 明确 81 实例、144 场、0 搜索，rho=1.10/1.25/1.50 是车队储备因子。它是容量输入，不是电动车占比敏感性结果。 |
| 仓库中任何 EV 组成结果 | 有旧诊断，但不是控制占比档 | `baselines/e2_alns/280kwh_fleet_composition_gate_data/`；`baselines/e2_alns/280kwh_fleet_composition_gate.md` | 直接可用 | 旧诊断为 280 kWh、17 个非 China81 实例、3 种子、153 行搜索和 51 个胜者；`conclusion.json:2-16` 为全 CV 1、全 EV 16、EV-heavy 34、balanced 0，状态 `HALT_EV_DOMINANT`。这些是优化后胜者按 EV 路线占比归类，不是预先固定 EV 占比档位的控制变量实验；只能回答“仓库确有历史 EV 组成诊断”。 |
| 当前 China81 按预设 EV 占比分档的成本、排放、用车与路线结果 | 没有 | 查不到；核对 `baselines/china_e3_e7/`、`fleet_caps.csv` 及上述历史 composition/battery 目录 | 必须重跑搜索 | `fleet_caps.csv.sensitivity_json` 改的是储备因子且保留全部 `R_d` 辆 CV；历史 `280kwh` 包按结果占比分组，`battery_spectrum_transition_data/full_gate_transition_summary.csv` 则扫描电池容量 80/100/113/141/210/280 kWh。仓库没有一份把 EV 可用量或占比设为 0%、…、100% 并在当前 77.28 kWh China81 上重新优化的正式结果。 |
| 当前正式解中 EV 名额是否实际约束结果 | 有 | `baselines/china_e3_e7/e4_joint_routing_20260801/formal_panel_20260801/*/decision.json` 与 `*/solutions/*.json` | 直接可用 | 对三成员包的 90 份解，按 `.solution.routes[].vehicle_type/home_depot_id` 统计各场实际 EV 数，并与 `decision.json.terminal_capacity_basis.*.ev_cap` 比较，得到 180/180 个“解×车场”单元均相等；`docs/handoff/e2_e7_decision_source_execution_audit_20260801.md:24` 也登记 `180/180`。这证明现有主档 EV 上限全触顶，但不能替代占比分档敏感性。 |

判定：`sensitivity_json` 的 1.10/1.25/1.50 不是 10%/25%/50% 电动车占比，而是以全燃油装箱路线数为基数的总车队储备因子。现有正式解又在 180/180 个车场单元触及 EV 上限，因此不能由单一主档外推车队电动化曲线。

## 5.3 动态需求触发台账

| 需要什么数据 | 仓库里有没有 | 路径 | 判定 | 判定理由 |
|---|---|---|---|---|
| O1 四种重算触发规则的低成本运行数据 | 有 | `baselines/china_e3_e7/e7_o1_replanning_20260801/probe_three_sizes_seeds1to3_eval8_count_20260801/` | 直接可用 | `decision.json:2-13` 为 36 单元、34 通过、`formal_result=false`、`research_effect_judged=false`；`metadata.json:6-18,27-34` 为 3 个规模、4 种规则、种子 1--3、每阶段 8 次评价且明确 `diagnostic_only_not_formal`。可直接用于说明现有触发器的技术表现，不能作为 5.3 正式效果。 |
| O1 两个失败单元的硬约束机理 | 有 | `baselines/china_e3_e7/e7_o1_replanning_20260801/failure_diagnosis_20260801/` | 直接可用 | `decision.json:2-19` 为 35 辆全在、19 辆可用、11 辆未出车，触发晚于深圳 CV 最迟出发 267.56694 秒，`higher_budget_can_rescue_current_stage=false`；`report.md:31-44` 给出 C135 的出现、触发及各车场最迟离场时间。可解释失败机理，不是效果比较。 |
| O2 发车等待时机的零搜索体检 | 有 | `baselines/china_e3_e7/e7_o2_dispatch_20260801/zero_search_15_streams_20260801/` | 直接可用 | `decision.json:2-13` 为 15 条流、300 单、0 搜索、0 求解、`formal_result=false`；`:52-61` 为等待 0/10/20/30 分钟后仍可达 300/298/295/293 单。`report.md:20` 明确 30 分钟只是观察点，D1/D2、等待损失和正式求解均未进入。 |
| 动态触发策略对成本、排放、等待、重算次数的正式配对效果 | 没有 | `baselines/china_e3_e7/e7_o1_replanning_20260801/` 与 `e7_o2_dispatch_20260801/` 均已核对 | 必须重跑搜索 | O1 `formal_result=false` 且 2/36 单元失败；O2 `o2_effect_experiment=false, search_evaluations=0, solver_runs=0`。仓库剩余的是事件流、触发批次、时间窗余量和失败诊断，没有可作为论文正式结果的完整配对搜索。 |

## 必须重跑搜索的最小充分规模

下列规模只取目标期刊同类论文实际使用过的最小实验形态，不设置项目自造的显著性门、改善率门或合格线。相对算力把一次完整 China81 单算例单种子静态求解记为 1 单位。

| 项目 | 最小充分规模与停止条件 | 目标期刊实际依据 | 相对算力 |
|---|---|---|---:|
| 当前车型 China81 五算法同协议比较 | 1 个 51--149 客户的当前 China81 实例；5 算法×10 种子，共 50 次。每次最大 2000 迭代，连续 150 次无改善即停，先到者停止。 | 陈婉茹等（2023）p.3328：所有算例结果基于 10 次运算，最大 2000 迭代，51--149 客户最大无改善 150；p.3331 表 8：在一个 71 客户仿真实例上比较多种算法并同时报 Best、Avg、Gap、时间。陈雨蝶等（2025）pp.13--14 表 6 也在一个仿真实例上逐次列出三算法的 10 次结果。 | 50 |
| 当前 MV-HGS-SP 一因素组件消融 | 1 个 51--149 客户实例；完整版+2 个各删除一个部件的变体，共 3 臂×10 种子=30 次；停止同上：最大 2000 迭代或连续 150 次无改善。 | 陈婉茹等（2023）p.3331 表 8：完整 PIVNS-SOA、去全局破坏修复的 PVNS-SOA、去并行局部搜索的 IVNS-SOA，共三臂；p.3328 规定 10 次及 2000/150 停止。 | 30 |
| 当前 China81 车队电动化配置敏感性 | 1 个 51--149 客户实例；固定总车队规模，EV/FV 从 0/6、1/5、…、6/0 共 7 档；每档 10 种子，共 70 次；最大 2000 迭代或连续 150 次无改善。 | 陈婉茹等（2023）p.3331 表 9：单个 71 客户实例、每场 6 辆、7 个动力配置档；p.3328 规定全部算例 10 次及 2000/150 停止。李得成等（2021）pp.1006--1007 另以两组数据、固定总车数 6、EV 数 0--6 的 7 档进行车型配比敏感性。 | 70 |
| 动态需求触发正式效果 | 1 个动态实例；3 种触发/调整策略×10 种子=30 个完整日场景；每个场景含 1 次预优化和 3 次动态调整。静态/预优化停止为种群 120、最大 2000 代；该文没有另报动态重优化的独立停止条件，因此不能从文献补造第二套停止数值。 | 姜广田等（2024）p.2372：21 店铺实验种群 120、最大 2000 代；pp.2373--2374：三个动态服务时间窗/调整时点；p.2377 表 14：周期性、连续性、本文策略各运行 10 次。 | 120 |

动态项的 120 单位按 `3 策略×10 重复×(1 次预优化+3 次重优化)` 计；这是完整求解调用数的等价估算。若动态阶段只优化剩余客户，其实际墙钟可能低于同规模全日 China81 求解，但仓库没有可把它换算成更小统一系数的正式标定数据。

## 停止条件

两部分均已完成，终态为 `R2_EVIDENCE_INVENTORY_COMPLETE`。
