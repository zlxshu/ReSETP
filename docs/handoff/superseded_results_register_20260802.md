# ReSETP 旧结果作废登记（2026-08-02）

## 1. 登记口径

本登记执行用户 2026-08-02 的明确决定：“以前的数据和设计几乎全部作废，以最新的为准。”本句不是删除授权。下列历史目录、原始行、清单和哈希全部原地保留，只改变其可引用状态。

新合同是：固定成本按实体车计费，`c_fix=170` 不变；多趟开启；车场充电并发默认不设上限；China81 默认车队 authority 改为总量固定的 v3。凡以“每条路线收一次固定成本”、有限车场并发、旧 v1/v2 车队构成或 `num_ev(d)=max(1,ceil(0.25*R_d))` 为数值基础的结果，均不能直接迁移到新合同。

状态标签只有四种：

- `NUMERICALLY_SUPERSEDED__DO_NOT_CITE_AS_RESULT`：成本、利润、节省、效应量或其排序受新计费口径影响，**不得作为结果引用**。
- `SETTING_SUPERSEDED__DO_NOT_CITE_AS_RESULT`：车队规模、车型构成、可行率或触发条件使用旧 authority，**不得作为结果引用**。
- `ENGINEERING_EVIDENCE_RETAINED__NOT_SCIENTIFIC_RESULT`：只保留接口、重放、逐位一致性或记账恒等式等工程证据；不得升级为论文科学结果。
- `UNAFFECTED_VALID_WITH_ORIGINAL_SCOPE`：经逐项判断不依赖本次改变，在原注册范围内仍有效。

## 2. 因计费口径变化而数值失效的结果包

### 2.1 E2 China81 五算法批

- 路径：`baselines/algorithm_prototypes/china81_vs_opensource_20260727/`。
- 原结果：2025 行（81 算例 × 5 电动化档 × 5 算法）；O 新跑 405 行、封存复用 1620 行；MV 对 O 为 354 胜、46 平、5 负，MV 相对 O 平均改善 1.9191180150%，单调阶梯 299/405。
- 失效依据：目标值按旧的路线固定费计算，且 China81 车型构成来自旧车队 authority；新合同改为按实体车计费并启用 v3。算法轨迹和旧解仍是历史溯源材料，但上述胜负、均值和阶梯计数必须在新合同下重算。
- 状态：`NUMERICALLY_SUPERSEDED__DO_NOT_CITE_AS_RESULT` + `SETTING_SUPERSEDED__DO_NOT_CITE_AS_RESULT`。**不得作为结果引用。**

### 2.2 E3 固定归属—联合优化正式面板

- 路径：`baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_solomon_i1_20260801/`。
- 原结果：60 个配对单元、120 行；联合成本 60/60 低于固定归属；总体平均降本 36.4772688111%，范围 30.9858064866%--42.3997108184%，平均里程下降 57.3723227311%，平均排放下降 57.3070703349%，平均车辆数变化 -2.95。早期 150c-01 三种子小面板为 37.4206%、37.8467%、38.2028%，均值约 37.8234%。
- 失效依据：两臂的成本、车辆数与车型构成均是在旧固定费和旧 authority 下得到；新合同既改变目标值又改变可用车队。客户“历史归属固定/允许跨承包商”的输入映射仍可作为设计来源，但不能保住原效应量。
- 状态：`NUMERICALLY_SUPERSEDED__DO_NOT_CITE_AS_RESULT` + `SETTING_SUPERSEDED__DO_NOT_CITE_AS_RESULT`。**原降本、车辆和排放效应不得作为结果引用。**

### 2.3 E3 分区—联合零搜索重放包

- 路径：`baselines/china_e3_e7/e3_zone_joint_20260731/`。
- 原结果：40 个正式单元；50c 行联合相对分区成本效应 2.2727594139%、车辆变化 -1、里程项 -28.0356615356%、碳项 -4.0448938636%；100c 行分别为 0.6931146752%、-0.8、-12.1766105814%、-1.1825313115%；两实例成本效应均值 1.4829370445%。
- 失效依据：零搜索只能证明对封存旧解的重放；旧解的成本和车型构成不满足新合同的结果口径。`IND_ZONE_mapping_identical=true` 是输入映射事实，可继续用于解释设计重合，但不使旧数值有效。
- 状态：`NUMERICALLY_SUPERSEDED__DO_NOT_CITE_AS_RESULT`。**上述数值不得作为结果引用。**

### 2.4 E4 固定路线 405×28 碳时序包

- 路径：`baselines/china_e3_e7/e4_carbon_timing_20260729/`。
- 原结果：11340 个配对行，即 405 个固定方案 × 28 天；充电排放下降 54.9703719988%（展示 54.97%）。该包另报告过系统排放约下降 9.7463%、电费约上升 134.8798%、总成本约上升 1.8454%。
- 失效依据：总成本百分比使用旧按路线固定费分母，不能沿用。固定充电会话在 ASAP/CARBON 两个时序下的逐会话用电与排放重放不依赖车队搜索，可保留为旧方案上的机制证据，但它不是 v3 车队下的新结果。
- 状态：成本项为 `NUMERICALLY_SUPERSEDED__DO_NOT_CITE_AS_RESULT`；逐会话排放重放为 `ENGINEERING_EVIDENCE_RETAINED__NOT_SCIENTIFIC_RESULT`。**不得把 54.97% 或 1.8454% 当作新合同结果引用。**

### 2.5 E4 三目标 90 行正式面板

- 路径：`baselines/china_e3_e7/e4_joint_routing_20260801/formal_panel_20260801/`。
- 原结果：30 个配对单元、COST_ONLY/COST_PLUS_CARBON/PURE_CARBON 三模式，共 90 行。COST_PLUS 相对 COST：充电排放 -18.1998955003%、电费 -0.7022608672%、运营成本 +0.0000448067%、系统排放 -2.6791434312%，路径改变 2/30；PURE 相对 COST：-89.2497233656%、+307.4133802850%、+2.4865635350%、-13.9353529701%，路径改变 19/30。
- 失效依据：三目标的成本分量和目标排序使用旧固定费，源方案使用旧 authority；即使此汇总本身不重新搜索，也不能把旧方案重放升级为新合同比较。
- 状态：`NUMERICALLY_SUPERSEDED__DO_NOT_CITE_AS_RESULT` + `SETTING_SUPERSEDED__DO_NOT_CITE_AS_RESULT`。**90 行及全部效应量不得作为结果引用。**

### 2.6 E5 非线性充电正式包

- 路径：`baselines/china_e3_e7/e5_nonlinear_final_20260730/`。
- 原结果：20/20 NL90 完整可行，L100 假可行 0/20，共同 NL90 物理下成本效应 0%；封存 196 个充电会话，其中 36 个会话时长增加，平均增加约 232.2701 秒、最大约 1264.5818 秒。
- 失效依据：成本效应以旧固定费为分母，方案又来自旧 authority。NL90 曲线对封存会话的算术差异仍可作为构造场景下的物理/实现观察，但不证明新合同下路线或系统效应。
- 状态：成本与系统结论为 `NUMERICALLY_SUPERSEDED__DO_NOT_CITE_AS_RESULT`；曲线逐会话核算为 `ENGINEERING_EVIDENCE_RETAINED__NOT_SCIENTIFIC_RESULT`。**0% 成本效应不得作为结果引用。**

### 2.7 E6 两成员公平与事后分配包

- 路径：`baselines/china_e3_e7/e6_fairness_v3_20260731/` 与 `baselines/china_e3_e7/e6_allocation_20260731/`。
- 原结果：公平包 20 单元，自然 Pareto 0/20、回退 `F=I` 为 20/20、公平代价 1.5117836669%、弱成员平均改善 755.0176659166 元；事后分配包 19/20 可转移支付，平均 Shapley 转移 817.3747565968 元，平均每成员净增益 22.6790754960 元；1 个单元系统节省 -1.1353774165 元。
- 失效依据：参与约束、合作剩余、转移额和公平代价都直接由旧成本账生成；按实体车计费会改变每个联盟和成员的成本，旧分配数值不能重用。预算平衡和利润守恒等恒等式可作实现核对，不是经济结果。
- 状态：`NUMERICALLY_SUPERSEDED__DO_NOT_CITE_AS_RESULT`；恒等式为 `ENGINEERING_EVIDENCE_RETAINED__NOT_SCIENTIFIC_RESULT`。**上述经济数值不得作为结果引用。**

### 2.8 E6 四承包商 900 联盟行正式面板及其派生账本

- 主包路径：`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/`。
- 主包原结果：60/60 完整单元、900/900 联盟行；大联盟相对四家单干成本节省均值 33.018%，范围 28.442%--37.145%；Shapley 在核内 52/60。
- 实际配送方收入账路径：`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6_serving_revenue_ledger_20260801/`。原结果为 60 单元、240 成员行，57/60 单元至少一成员低于单干，86/240 成员行为负，最低预结算增益 -9442.6840863941 元。
- 核仁路径：`baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6s2_nucleolus_20260801/`。原结果为核仁在核内 60/60、Shapley 在核内 52/60、最低成员增益 265.9977564702 元。
- 失效依据：三个包逐层继承同一套旧联盟成本；按实体车计费会改变联盟特征函数、自然账利润、核和分配。因此 900 行及全部下游数值一起失效，但目录不得删除。
- 状态：三个包均为 `NUMERICALLY_SUPERSEDED__DO_NOT_CITE_AS_RESULT` + `SETTING_SUPERSEDED__DO_NOT_CITE_AS_RESULT`。**900 行、大联盟节省、参与率、Shapley/核仁判断均不得作为结果引用。**

### 2.9 E7 动态实验包

- 路径：`baselines/china_e3_e7/e7_dynamic_v3_20260731/`；相关旧触发包：`baselines/china_e3_e7/e7_trigger_policies_20260801/`。
- 原结果：v3 登记 120 单元，仅 50c 有 6 个合法单元，100c/150c 为 0；更早触发比较曾报混合触发相对 30 分钟低 1.73%、逐单触发低 7.16%。
- 失效依据：v3 的车队不足诊断建立在旧 authority；1.73%/7.16% 又已因主动经济拒单偏离“整批新单全部接收”的母体而在 2026-08-01 撤出。现在再叠加按实体车计费，旧动态成本排序没有引用资格。
- 状态：`SETTING_SUPERSEDED__DO_NOT_CITE_AS_RESULT` + `NUMERICALLY_SUPERSEDED__DO_NOT_CITE_AS_RESULT`。**不可行率和旧触发成本差均不得作为结果引用。**

## 3. 因车队 authority 变化而设定失效的包

### 3.1 v1/v2 authority 本体

- 路径：`data/ChinaInstances/china81_finite_fleet_authority_v1_20260728/` 与 `data/ChinaInstances/china81_finite_fleet_authority_v2_20260728/`。
- 原设定：v1/v2 沿用 `num_ev(d)=max(1,ceil(0.25*R_d))` 一类无文献出处的按路线数缩放公式，并以单趟装箱路线数为车队基数；旧文件和原哈希继续保留作版本史。
- 失效依据：2026-08-02 文献核对的 7/7 合格多趟论文均按车队总量固定，无一随多趟按比例缩小；6/7 不设每车每日趟数上限。新 v3 以五档同时可行的最小总规模为 authority。
- 状态：`SETTING_SUPERSEDED__DO_NOT_CITE_AS_RESULT`。**不得再作为 China81 默认设定或论文结果引用；只允许显式选择用于历史复算。**

### 3.2 单趟总量与旧并发诊断

- 路径：`docs/handoff/fleet_sizing_derivation_20260802/`。
- 原设定/结果：Convention B 单趟装箱总量 1042；在旧有限车场并发下五档零搜索认证为 81/81/81/81/75，W1 放开默认并发后同一旧车队变为 81/81/81/81/81。
- 失效依据：W1 的 81/81/81/81/81 只证明放开并发解决旧车队下的 6 个 100% EV 冲突；它没有证明 1042 是多趟条件下的最小实体车总量。v3 已把默认总量重锚为 943。
- 状态：1042 作为当前 authority 为 `SETTING_SUPERSEDED__DO_NOT_CITE_AS_RESULT`；W1 前后并发对照保留为历史诊断。**不得把 1042 作为新合同车队上限引用。**

### 3.3 多趟 Convention A 缩放诊断

- 路径：`docs/handoff/fleet_sizing_multitrip_20260802/`。
- 原设定/结果：Convention A 总量 695，五档认证 81/81/78/63/41。
- 失效依据：该设计把车队数随多趟路线数缩小，和 7/7 目标文献的总量固定口径相反；它只是一条已经否决的诊断路线。
- 状态：`SETTING_SUPERSEDED__DO_NOT_CITE_AS_RESULT`。**695 和对应可行率不得作为结果或默认设定引用。**

### 3.4 充电器与车队依据汇总中的旧总量

- 路径：`docs/handoff/charger_and_fleet_basis_20260802/`。
- 原设定：其中 Convention B 的 1042 与旧单趟总量一致；文献表同时记录了总量固定和多趟上限信息。
- 失效依据：汇总中的 1042 已由 v3 的 943 取代，但逐篇文献摘录不因数值重锚而失效。
- 状态：1042 为 `SETTING_SUPERSEDED__DO_NOT_CITE_AS_RESULT`；逐篇文献证据仍有效，引用时必须回到页级来源。

## 4. 仍然有效或仅保留工程意义的部分

### 4.1 公开算例上的算法质量

- 路径：`baselines/algorithm_foundation/mdvrptw_v13_comparison_20260719/`。
- 保留依据：这是公开 MDVRPTW 算例的零搜索语义/BKS 基础核对，不使用 China81 的固定费或 fleet authority。
- 状态：`UNAFFECTED_VALID_WITH_ORIGINAL_SCOPE`。仍可在其原注册范围内引用，不得外推为新 China81 结果。

- 路径：`baselines/e2_final_campaign_20260720/mv_hgs_sp_final/p1_formal_gate/`。
- 原结果：28 个公开算例、280 个种子单元；相对母体为 264 胜、16 平、0 负，混合算法平均误差 0.9048706%，未产生新 BKS。
- 保留依据：公开算例的距离目标与算法比较不依赖 China81 的 `c_fix` 计费或车队 authority。
- 状态：`UNAFFECTED_VALID_WITH_ORIGINAL_SCOPE`。

### 4.2 新合同公式与并发开关的单元证据

- 路径：`baselines/china_e3_e7/formula_change_20260802/`。
- 保留依据：W1 的按实体车计费算术、`c_fix=170`、显式旧有限并发配置和默认无并发上限，是本次 v3 的前置合同；它们在当前源上通过五项不变量。W1 报告中的 1042 仅是旧车队对照，不是 v3 authority。
- 状态：合同与测试部分为 `UNAFFECTED_VALID_WITH_ORIGINAL_SCOPE`；1042 的当前设定资格已在 3.2 撤销。

### 4.3 多趟接口和逐位重放兼容性

- 路径：`baselines/china_e3_e7/multitrip_interface_completion_20260802/`。
- 原工程结果：E4 90/90、E6 900/900 接口核对通过；E4 810 条原路线压为 786 辆实体车，E6 14252 条路线压为 14195 辆实体车。
- 保留依据：这些数只证明“旧封存解能被新计费器确定性地识别实体车并逐位重放”，没有比较新旧方案质量，也没有产生新路径。
- 状态：`ENGINEERING_EVIDENCE_RETAINED__NOT_SCIENTIFIC_RESULT`。可用于证明兼容性，**不得把车辆节省或旧成本转写成论文结果。**

- 路径：`baselines/china_e3_e7/blocker_fix_20260802/`。
- 原工程结果：多趟关闭 30+30 个单元逐位一致，多趟开启 30+30 个单元通过新语义认证。
- 保留依据：逐位一致性/合法性属于实现回归，和旧效应量是否仍可引用是两件事。
- 状态：`ENGINEERING_EVIDENCE_RETAINED__NOT_SCIENTIFIC_RESULT`。

- 路径：`baselines/china_e3_e7/current_source_compatibility_20260801/saved_solution_replay_20260801/`。
- 原工程结果：3009/3015 个封存方案可按当时当前源重放，另有 6 个 E2 单元 HALT。
- 保留依据：它保存的是源—档案兼容性和失败定位，不是新合同的科学效应；源继续变化后应以新回归为准。
- 状态：`ENGINEERING_EVIDENCE_RETAINED__NOT_SCIENTIFIC_RESULT`。

### 4.4 文献 authority 证据与不受影响的静态输入

- 路径：`docs/handoff/multitrip_fleet_literature_20260802/`。
- 保留依据：7/7 总量固定、6/7 不设每车每日趟数上限来自已核过的逐篇页级证据，是 v3 的外部依据，不依赖旧实验数值。
- 状态：`UNAFFECTED_VALID_WITH_ORIGINAL_SCOPE`。

- 路径：`data/ChinaInstances/` 中除 fleet authority 目录外的已冻结需求、坐标、距离/时间矩阵和车型技术参数 authority。
- 保留依据：本次改的是固定费计费对象、车场并发默认值和车队上限；没有授权改写这些静态输入。它们是否适合新的论文主张仍须按各自 provenance 审核，但没有因 W2 自动作废。
- 状态：`UNAFFECTED_VALID_WITH_ORIGINAL_SCOPE`。

## 5. 使用纪律

旧目录不删除、不移动、不覆盖。需要复核历史差异时，必须同时标明旧合同和旧 authority；任何面向正文、表格、摘要或投稿材料的结果引用，均须来自新合同与 v3 authority 下重新注册的结果包。工程重放 PASS 不能替代重新求解，也不能把旧效应量恢复为有效。
