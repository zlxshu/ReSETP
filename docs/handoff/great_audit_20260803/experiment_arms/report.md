# GR2 实验对照臂的真实差异审核

状态：`GR2_EXPERIMENT_ARMS_AUDIT_COMPLETE`。

## 结论先行

本轮按保守并集覆盖了 `baselines/` 下 **138/138** 个带正式生命周期标记且含 `metadata.json` 的包，剩余 **0**。其中包括 60 个 E6-A 正式单元、已封存包、已作废/HOLD/preflight 包，以及一个 `formal_result=false` 但会被正式文本索引命中的诊断包。判定为：`一致` 34 包，`多差了东西` 75 包，`少差了东西` 16 包，`不可核验（配置未登记）` 13 包。这里的“包数”不是独立科学问题数；60 个 E6-A 单元逐包计数。

没有一个基准可核为“观测到的现实运营做法”。5 个包的基准是可执行但构造的规则，124 个是模型/算法/责任图构造，9 个没有执行对照臂。因而即使 verdict=`一致`，也只说明 runner 的实际开关与包内声明一致，不把构造场景升级为现实发现。

## 足以改变当前引用口径的发现

1. **五算法 China81 比较不是等协议算法比较。** 原文已经承认 O 是 07-27 的 `NoImprovement(3000)` 新跑，F/E/M/MV 是 07-24 每视角固定 25000 次的 1620 行封存复用，且不能声称同批、同机、同停止规则、等计算量。批次、预算、停止规则、共同初始解与代码哈希无法同时对齐；预算/停止规则足以单独成为所报性能差异的替代解释。

2. **P1 的“MV-HGS-SP 胜 HGS 母体”是嵌套继续搜索。** runner 先完整运行 mother，再把 mother 的最优解、精英与路线池交给 hybrid，hybrid 继续最多四个 epoch 和 SP，并取包含 mother 的最优值。于是 0 负由构造保证，额外预算、热启动和停止规则足以解释 264 胜。

3. **历史 E3 mismatch 的合作臂拥有 10 倍搜索预算。** 独立臂每场 200、合计 400，合作臂 4000；同时共同起点、车队可行域语义和归属图重复均不对称。它不能作为“只改变客户归属/合作权限”的证据。

4. **当前 E6-A 的 coalition 比较并非共同起点、等总计算量。** 每个 coalition 从自己的合法基础方案出发；四家单干成本是四份 singleton 搜索之和，大联盟是一份搜索。4:1 搜索量反而偏向单干，因此不能单独制造当前 28%--37% 的大联盟优势；但不同初始解与无现实出处的 capacity-rank-aligned 客户责任可以成为替代解释。

5. **E7 正式谱系混有代码版本和不等预算。** 102 个父任务与 18 个边界修复子任务混用，两个四臂配对单元内部版本不同；`simple_insertion` 每事件 1 次主评价，其他搜索臂 50 次。代码修复或预算差异均足以单独解释相应比较的一部分。

6. **当前算法/消融包的“同上限”不是“同实际计算量”。** 算法种群数和组件开关改变了无改善停止的实际迭代/完整评价/CPU。现有结果全部同值，因此该差异没有制造当前零效应；它仍禁止等计算量表述。

7. **当前 E3 Solomon-I1 两臂实现本身对称，但基准是构造的。** runner 只切 `hard_home_depot_lock`，seed、共同初始解、车型、上限和预算一致；所谓历史客户归属来自 `source_p_sequences.csv` 的构造标签与容量—需求排序，没有企业历史记录出处，且处理臂改派比例很大。可支持的是“该构造责任图下的联合重分配效应”。

## 判定方法

“声称的对照”引用各包 `report.md`/`decision.json` 原文；无这两者的两个预注册/HALT 包只引用 `metadata.json` 并判为不可完整核验。“实际的差异”回到 metadata、runner/config、raw runs、种子、预算、停止规则和哈希字段。`一致` 不等于有效或真实；`多差了东西` 指除声明因素外还存在批次/机器/预算/停止/种子/起点/evaluator/代码等差异；`少差了东西` 指声明处理没有触发或臂未执行完；`不可核验` 指没有足够臂级配置。

## 基准性质边界

`观测的`要求基准直接来自可追溯的企业/现场排班、归属或决策记录；本轮为 0。`构造出来但可执行`包括 ASAP/立即充电等可机械执行规则，但它们不是已观测实践。其余算法母体、随机/排序客户责任、冻结订单流、车队比例、联盟值和目标函数控制均为构造基准。构造参数只能支持该构造场景下的观察。

## 全包清单

下表每行对应 `arms_audit.json` 的一条记录；详细原文、实际差异、额外差异逐项解释和实施证据均在 JSON 中。

|序号|package_path|生命周期|判定|基准性质|关键边界|
|---:|---|---|---|---|---|
|1|`baselines/algorithm_prototypes/china81_vs_opensource_20260727`|封存比较，当前仍被引用但协议不共线|多差了东西|构造出来的|批次；机器；预算；停止规则；车型；车队上限；随机种子；初始解；评价器版本；代码哈希|
|2|`baselines/china_e3_e7/formal_algorithm_20260802`|当前主线正式完成，但判别力为零|多差了东西|构造出来的|预算；停止规则|
|3|`baselines/china_e3_e7/formal_ablation_200c_20260803`|当前主线正式完成，三臂同值|多差了东西|构造出来的|预算；停止规则|
|4|`baselines/china_e3_e7/formal_fleet_levels_20260802`|当前主线正式包；75%/100% 臂在搜索前失败|少差了东西|构造出来的|因此实际只执行了 3/5 个车队档位的处理比较。|
|5|`baselines/china_e3_e7/formal_dynamic_dispatch_20260802`|当前 XC2 动态发车正式完成|一致|构造出来的|实现差异与声明一致|
|6|`baselines/china_e3_e7/carbon_timing_rescore_20260802`|当前合同重评分 HALT；零搜索重建完成但不构成当前合同正式比较|少差了东西|构造出来但可执行|没有完成所需的 247 个来源路线搜索和 90 个联合搜索，因此“当前合同”两臂不存在完整可比搜索。|
|7|`baselines/china_e3_e7/carbon_timing_rescore_20260802/.recovery_attempt4_concurrent_writer_corrupt_20260803`|并发写入损坏快照；已作废、浅审|不可核验（配置未登记）|构造出来但可执行|目录被明确隔离为 concurrent-writer corrupt；不具备可信的完整臂级配置/证书。|
|8|`baselines/china_e3_e7/carbon_timing_rescore_20260802_attempt1_invalid`|已作废 attempt1；浅审|少差了东西|构造出来但可执行|decision 将本尝试标为无效；臂级证书不满足后续正式口径。|
|9|`baselines/china_e3_e7/e3_environment_authority_20260723`|正式边界/审计包；无独立执行对照臂|不可核验（配置未登记）|不适用：无执行对照臂|metadata/decision/report 没有给出可从 runner 逐臂复现的两个执行配置。|
|10|`baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_20260801/cn-prd-150c-01-V2-LOCATIONS`|已被 Solomon-I1 面板取代；旧面板成员|一致|构造出来的|实现差异与声明一致|
|11|`baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_20260801/cn-prd-150c-02-V2-LOCATIONS`|已被 Solomon-I1 面板取代；旧面板成员|一致|构造出来的|实现差异与声明一致|
|12|`baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_20260801/cn-prd-150c-03-V2-LOCATIONS`|已被 Solomon-I1 面板取代；搜索前 HALT|少差了东西|构造出来的|共同初始路线在搜索前违反车队上限；两臂未形成完成的搜索对照。|
|13|`baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_20260801/cn-prd-200c-01-V2-LOCATIONS`|已被 Solomon-I1 面板取代；搜索前 HALT|少差了东西|构造出来的|共同初始路线在搜索前违反车队上限；两臂未形成完成的搜索对照。|
|14|`baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_20260801/cn-prd-200c-02-V2-LOCATIONS`|已被 Solomon-I1 面板取代；旧面板成员|一致|构造出来的|实现差异与声明一致|
|15|`baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_20260801/cn-prd-200c-03-V2-LOCATIONS`|已被 Solomon-I1 面板取代；旧面板成员|一致|构造出来的|实现差异与声明一致|
|16|`baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_solomon_i1_20260801/cn-prd-150c-01-V2-LOCATIONS`|当前 E3 Solomon-I1 正式面板成员|一致|构造出来的|实现差异与声明一致|
|17|`baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_solomon_i1_20260801/cn-prd-150c-02-V2-LOCATIONS`|当前 E3 Solomon-I1 正式面板成员|一致|构造出来的|实现差异与声明一致|
|18|`baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_solomon_i1_20260801/cn-prd-150c-03-V2-LOCATIONS`|当前 E3 Solomon-I1 正式面板成员|一致|构造出来的|实现差异与声明一致|
|19|`baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_solomon_i1_20260801/cn-prd-200c-01-V2-LOCATIONS`|当前 E3 Solomon-I1 正式面板成员|一致|构造出来的|实现差异与声明一致|
|20|`baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_solomon_i1_20260801/cn-prd-200c-02-V2-LOCATIONS`|当前 E3 Solomon-I1 正式面板成员|一致|构造出来的|实现差异与声明一致|
|21|`baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_solomon_i1_20260801/cn-prd-200c-03-V2-LOCATIONS`|当前 E3 Solomon-I1 正式面板成员|一致|构造出来的|实现差异与声明一致|
|22|`baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_solomon_i1_20260801/panel_summary`|当前 E3 Solomon-I1 正式面板汇总|一致|构造出来的|实现差异与声明一致|
|23|`baselines/china_e3_e7/e3_zone_joint_20260731`|旧 E3 区域—联合正式比较|一致|构造出来的|实现差异与声明一致|
|24|`baselines/china_e3_e7/e4_carbon_timing_20260729`|封存的固定路线零搜索正式重放|一致|构造出来但可执行|实现差异与声明一致|
|25|`baselines/china_e3_e7/e4_joint_routing_20260801/formal_panel_20260801`|旧合同下 E4 联合路由正式包|一致|构造出来的|实现差异与声明一致|
|26|`baselines/china_e3_e7/e4_joint_routing_20260801/formal_panel_20260801/cn-prd-50c-01-V2-LOCATIONS`|旧合同下 E4 联合路由正式包|一致|构造出来的|实现差异与声明一致|
|27|`baselines/china_e3_e7/e4_joint_routing_20260801/formal_panel_20260801/cn-prd-50c-02-V2-LOCATIONS`|旧合同下 E4 联合路由正式包|一致|构造出来的|实现差异与声明一致|
|28|`baselines/china_e3_e7/e4_joint_routing_20260801/formal_panel_20260801/cn-prd-50c-03-V2-LOCATIONS`|旧合同下 E4 联合路由正式包|一致|构造出来的|实现差异与声明一致|
|29|`baselines/china_e3_e7/e5_enroute_nonlinear_20260801/b2_low_cost_diagnostic_20260801`|formal_result=false 的诊断包；保守纳入防漏|一致|构造出来的|实现差异与声明一致|
|30|`baselines/china_e3_e7/e5_nonlinear_final_20260730`|封存 E5 正式比较|一致|构造出来的|实现差异与声明一致|
|31|`baselines/china_e3_e7/e6_allocation_20260731`|封存 E6 事后分配包|不可核验（配置未登记）|构造出来的|metadata/raw_runs 登记 search=0；逐种子复用同一 I/U 成本，Shapley/core 为事|
|32|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6_serving_revenue_ledger_20260801`|当前论文仍引用的 E6 收入账本后处理|一致|构造出来的|实现差异与声明一致|
|33|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-150c-01-V2-LOCATIONS/seed_01`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|34|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-150c-01-V2-LOCATIONS/seed_02`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|35|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-150c-01-V2-LOCATIONS/seed_03`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|36|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-150c-01-V2-LOCATIONS/seed_04`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|37|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-150c-01-V2-LOCATIONS/seed_05`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|38|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-150c-01-V2-LOCATIONS/seed_06`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|39|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-150c-01-V2-LOCATIONS/seed_07`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|40|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-150c-01-V2-LOCATIONS/seed_08`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|41|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-150c-01-V2-LOCATIONS/seed_09`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|42|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-150c-01-V2-LOCATIONS/seed_10`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|43|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-150c-02-V2-LOCATIONS/seed_01`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|44|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-150c-02-V2-LOCATIONS/seed_02`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|45|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-150c-02-V2-LOCATIONS/seed_03`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|46|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-150c-02-V2-LOCATIONS/seed_04`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|47|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-150c-02-V2-LOCATIONS/seed_05`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|48|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-150c-02-V2-LOCATIONS/seed_06`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|49|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-150c-02-V2-LOCATIONS/seed_07`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|50|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-150c-02-V2-LOCATIONS/seed_08`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|51|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-150c-02-V2-LOCATIONS/seed_09`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|52|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-150c-02-V2-LOCATIONS/seed_10`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|53|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-150c-03-V2-LOCATIONS/seed_01`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|54|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-150c-03-V2-LOCATIONS/seed_02`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|55|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-150c-03-V2-LOCATIONS/seed_03`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|56|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-150c-03-V2-LOCATIONS/seed_04`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|57|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-150c-03-V2-LOCATIONS/seed_05`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|58|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-150c-03-V2-LOCATIONS/seed_06`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|59|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-150c-03-V2-LOCATIONS/seed_07`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|60|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-150c-03-V2-LOCATIONS/seed_08`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|61|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-150c-03-V2-LOCATIONS/seed_09`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|62|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-150c-03-V2-LOCATIONS/seed_10`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|63|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-200c-01-V2-LOCATIONS/seed_01`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|64|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-200c-01-V2-LOCATIONS/seed_02`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|65|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-200c-01-V2-LOCATIONS/seed_03`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|66|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-200c-01-V2-LOCATIONS/seed_04`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|67|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-200c-01-V2-LOCATIONS/seed_05`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|68|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-200c-01-V2-LOCATIONS/seed_06`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|69|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-200c-01-V2-LOCATIONS/seed_07`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|70|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-200c-01-V2-LOCATIONS/seed_08`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|71|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-200c-01-V2-LOCATIONS/seed_09`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|72|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-200c-01-V2-LOCATIONS/seed_10`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|73|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-200c-02-V2-LOCATIONS/seed_01`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|74|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-200c-02-V2-LOCATIONS/seed_02`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|75|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-200c-02-V2-LOCATIONS/seed_03`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|76|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-200c-02-V2-LOCATIONS/seed_04`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|77|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-200c-02-V2-LOCATIONS/seed_05`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|78|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-200c-02-V2-LOCATIONS/seed_06`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|79|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-200c-02-V2-LOCATIONS/seed_07`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|80|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-200c-02-V2-LOCATIONS/seed_08`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|81|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-200c-02-V2-LOCATIONS/seed_09`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|82|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-200c-02-V2-LOCATIONS/seed_10`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|83|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-200c-03-V2-LOCATIONS/seed_01`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|84|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-200c-03-V2-LOCATIONS/seed_02`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|85|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-200c-03-V2-LOCATIONS/seed_03`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|86|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-200c-03-V2-LOCATIONS/seed_04`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|87|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-200c-03-V2-LOCATIONS/seed_05`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|88|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-200c-03-V2-LOCATIONS/seed_06`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|89|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-200c-03-V2-LOCATIONS/seed_07`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|90|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-200c-03-V2-LOCATIONS/seed_08`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|91|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-200c-03-V2-LOCATIONS/seed_09`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|92|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/units/cn-prd-200c-03-V2-LOCATIONS/seed_10`|当前 E6-A 正式单元|多差了东西|构造出来的|预算；初始解|
|93|`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6s2_nucleolus_20260801`|当前论文仍引用的 E6-S2 核仁后处理|一致|构造出来的|实现差异与声明一致|
|94|`baselines/china_e3_e7/e6_fairness_v3_20260731`|封存 E6 公平候选池比较|一致|构造出来的|实现差异与声明一致|
|95|`baselines/china_e3_e7/formal_fleet_levels_20260802_presearch_halt_sem_nsems_max`|预搜索 HALT/未完成正式臂|少差了东西|构造出来的|车队上限方案改变，但处理臂未完整执行。|
|96|`baselines/china_e3_e7/foundation_20260723`|正式搜索 HELD 的规划底座；无执行对照臂|不可核验（配置未登记）|不适用：无执行对照臂|formal_search_allowed=false；没有逐臂 seed、预算或结果。|
|97|`baselines/algorithm_foundation/mdvrptw_v13_comparison_20260719`|正式边界/审计包；无独立执行对照臂|不可核验（配置未登记）|不适用：无执行对照臂|metadata/decision/report 没有给出可从 runner 逐臂复现的两个执行配置。|
|98|`baselines/contract_audit/e1_e7_submission_contract_20260711`|正式边界/审计包；无独立执行对照臂|不可核验（配置未登记）|不适用：无执行对照臂|metadata/decision/report 没有给出可从 runner 逐臂复现的两个执行配置。|
|99|`baselines/e1_model/e1_submission_20260711_committed/formal`|历史 E1 模型结构正式门|少差了东西|构造出来的|mixed vs CV-only 的车型可行域是声明处理；共同种子/费用证书存在。|
|100|`baselines/e2_alns/e2_16000_preflight_20260712/formal`|历史 E2 16000 评价 preflight|一致|构造出来的|实现差异与声明一致|
|101|`baselines/e2_alns/e2_80k_robustness_20260711/formal`|被 fixed 包取代的未完成 80k formal 目录|不可核验（配置未登记）|构造出来的|metadata 声明36行/24 tasks、4000预算、shared_start；目录没有 final decis|
|102|`baselines/e2_alns/e2_80k_robustness_fixed_20260711/formal`|历史 E2 80 kWh 正式镜像门|一致|构造出来的|实现差异与声明一致|
|103|`baselines/e2_alns/e2_final_10seed_20260711/formal`|历史 E2 九算法十种子正式收口|多差了东西|构造出来的|批次；机器|
|104|`baselines/e2_alns/e2_loss_recovery_20260711/short_gate_formal_start`|历史 E2 loss-recovery 短门；候选被拒|一致|构造出来的|实现差异与声明一致|
|105|`baselines/e2_alns/e2b_component_ablation_formal_20260715`|封存 E2b 四臂消融|一致|构造出来的|实现差异与声明一致|
|106|`baselines/e2_alns/homberger_g1_true_swapstar_risk_gate_20260718`|正式 G1 前风险门；HOLD、非正式性能结果|少差了东西|构造出来的|候选算子未实际触发，因而缺少声称的处理差异。|
|107|`baselines/e2_alns/homberger_g1_true_swapstar_risk_gate_v2_20260718`|正式 G1 前风险门；HOLD、非正式性能结果|少差了东西|构造出来的|候选算子未实际触发，因而缺少声称的处理差异。|
|108|`baselines/e2_alns/solomon_sintef_formal_bundles_20260717_v2`|正式输入/选择门；无执行对照臂|不可核验（配置未登记）|不适用：无执行对照臂|算例/BKS 适配门，search=0；没有算法对照臂。|
|109|`baselines/e2_alns/solomon_sintef_formal_bundles_20260717_v3`|正式输入/选择门；无执行对照臂|不可核验（配置未登记）|不适用：无执行对照臂|算例/BKS 适配门，search=0；没有算法对照臂。|
|110|`baselines/e2_final_campaign_20260720/mv_hgs_sp_final/p1_formal_gate`|封存 E2 公开题正式批|多差了东西|构造出来的|预算；停止规则；随机种子；初始解|
|111|`baselines/e2_final_campaign_20260720/mv_hgs_sp_final/p3_china81_gate`|封存 P3 China81 三臂正式批|多差了东西|构造出来的|预算；停止规则；随机种子；初始解|
|112|`baselines/e2_final_campaign_20260720/rce_hgs_proxy_misrank_gate_20260725/formal`|正式 RCE proxy 零搜索 STOP 门|少差了东西|构造出来的|576候选、HGS searches=0、accepted=0；预期处理没有触发。|
|113|`baselines/e3_ablation/e3_medium_paired_cost_formal_20260715`|历史 E3 中等责任偏离正式包|一致|构造出来的|实现差异与声明一致|
|114|`baselines/e3_ablation/e3_mismatch_formal_20260713_25`|历史 E3 mismatch 正式包；后续法证判为责任错配|多差了东西|构造出来的|预算；初始解；车队上限；随机种子|
|115|`baselines/e3_ablation/e3_mismatch_formal_20260713_50`|历史 E3 mismatch 正式包；后续法证判为责任错配|多差了东西|构造出来的|预算；初始解；车队上限；随机种子|
|116|`baselines/e3_ablation/e3_paired_cost_formal_20260713`|被 v2 取代的原始正式 HALT 包|少差了东西|构造出来的|声明了共同起点与共同预算，但0/48完成，没有实际处理差异。|
|117|`baselines/e3_ablation/e3_paired_cost_formal_v2_20260713`|历史 E3 配对成本正式包|一致|构造出来的|实现差异与声明一致|
|118|`baselines/e3_ablation/e3_submission_20260711/formal`|历史 E3 M0--M5 累积消融正式门|一致|构造出来的|实现差异与声明一致|
|119|`baselines/e3_ablation/e3_v11_clean_20260713/formal70`|正式边界/审计包；无独立执行对照臂|不可核验（配置未登记）|不适用：无执行对照臂|metadata/decision/report 没有给出可从 runner 逐臂复现的两个执行配置。|
|120|`baselines/e4_e5/china_2025_formal_month_selection_20260718`|正式输入/选择门；无执行对照臂|不可核验（配置未登记）|不适用：无执行对照臂|结果盲月份选择，search=0；没有处理臂—对照臂。|
|121|`baselines/e4_e5/e4_forecast_timing_formal_20260713`|历史 E4 固定配送充电时机正式复算|一致|构造出来但可执行|实现差异与声明一致|
|122|`baselines/e6_fairness/e6_participation_formal_20260714`|历史 E6 参与约束正式包|一致|构造出来的|实现差异与声明一致|
|123|`baselines/e6_fairness/e6_participation_formal_20260714/superseded/461f05ee25ed`|已 superseded 的 2/54 probe 快照；浅审|少差了东西|构造出来的|只完成2/54，不能形成正式全分母。|
|124|`baselines/e6_fairness/e6_participation_formal_20260714/superseded/9b6219b381aa`|已 superseded 的 2/54 probe 快照；浅审|少差了东西|构造出来的|只完成2/54，不能形成正式全分母。|
|125|`baselines/e7_dynamic/e7_dynamic_emission_intensity_formal_20260714`|旧 E7 动态结果的正式事后审计|多差了东西|构造出来的|初始解；初始/动态工作量|
|126|`baselines/e7_dynamic/e7_ex_post_participation_formal_20260714`|旧 E7 动态结果的正式事后审计|多差了东西|构造出来的|初始解；初始/动态工作量|
|127|`baselines/e7_dynamic/e7_full_day_value_audit_formal_20260714`|旧 E7 动态结果的正式事后审计|多差了东西|构造出来的|初始解；初始/动态工作量|
|128|`baselines/e7_dynamic/e7_multinetwork_formal_20260715`|封存 E7 父—子谱系正式证据；带失败|多差了东西|构造出来的|代码哈希；预算；初始解|
|129|`baselines/e7_dynamic/e7_multinetwork_formal_timing_clean_rerun_20260717`|旧 E7 计时污染清洁重跑记录|一致|构造出来的|实现差异与声明一致|
|130|`baselines/e7_dynamic/e7_multinetwork_independent_audit_20260715`|源 E7 结果的独立审计/旧快照；无新搜索|多差了东西|构造出来的|代码哈希；预算|
|131|`baselines/e7_dynamic/e7_multinetwork_independent_audit_20260715_pre_hygiene_patch_20260718`|源 E7 结果的独立审计/旧快照；无新搜索|多差了东西|构造出来的|代码哈希；预算|
|132|`baselines/e7_dynamic/e7_multinetwork_preflight_v4_20260715`|已被正式 E7 取代的 preflight；浅审|少差了东西|构造出来的|每次搜索仅2次评价，且存在2个失败任务；未达到正式批50次搜索臂预算。|
|133|`baselines/e7_dynamic/e7_multinetwork_preflight_v5_20260715`|已被正式 E7 取代的 preflight；浅审|少差了东西|构造出来的|每次搜索仅2次评价，且存在2个失败任务；未达到正式批50次搜索臂预算。|
|134|`baselines/e7_dynamic/e7_v2_20260714/formal`|被后续修复取代的 E7 formal HALT|少差了东西|构造出来的|未完成全分母，也未登记共同初始方案哈希。|
|135|`baselines/e7_dynamic/e7_v2_20260714/formal_batched_400_asset_aware`|被 shared-start/route-fix 包取代|不可核验（配置未登记）|构造出来的|同订单流与400/stage 已登记。|
|136|`baselines/e7_dynamic/e7_v2_20260714/formal_batched_400_asset_aware_audit`|旧 E7 batched 包的机械审计；合作推断 HALT|多差了东西|构造出来的|初始解|
|137|`baselines/e7_dynamic/e7_v2_20260714/formal_shared_start_400_route_fix`|E7 共享起点/路线身份修复后的正式短检查|一致|构造出来的|实现差异与声明一致|
|138|`baselines/e7_dynamic/m1_dynamic_truth_gate_20260711/e2_replay_post_dynamic_port`|正式边界/审计包；无独立执行对照臂|不可核验（配置未登记）|不适用：无执行对照臂|metadata/decision/report 没有给出可从 runner 逐臂复现的两个执行配置。|


## 覆盖与停止条件

仓库扫描时共有 2850 个 `baselines/**/metadata.json`。窄口径正式索引命中 98 个包；再把当前新增包、正式 schema/目录、手工登记正式边界、作废恢复快照及可能被旧索引漏掉的包做并集，增加 40 个，最终 138 个。显式 `NOT_FORMAL`、`NONFORMAL`、`NON_FORMAL` 包不因正文中出现“formal”而纳入。生成器对 138 个路径逐一强制匹配；任何重复或未匹配路径都会失败。本次匹配 138、遗漏 0，因此终态为 `GR2_EXPERIMENT_ARMS_AUDIT_COMPLETE`。

本任务没有运行 solver、runner、测试或实验；没有修改任何已有文件。只新增本目录内四个交付文件。
