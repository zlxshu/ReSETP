# 建模、单位与参数变更审批登记

## 强制规则

从2026-07-18起，任何直接影响数学模型、物理模型、成本口径或实验含义的变更，以及任何新方法，必须完成“提出—溯源—独立核验—影响分析—用户明确批准—代码与合同同步—回归测试—证据封存”八步后才能进入正式链。

必须审批的事项包括：单位或币种转换；体积、重量、时间、距离、速度、能量、功率和排放之间的转换公式；把观测数据改造成代理变量；目标函数、约束、可行性定义和违约惩罚；默认参数及主/敏感性情景；车辆、车场、充电桩、时间窗和需求的语义；算例生成、抽样、配额、插补和筛选方法；道路矩阵、能耗和充电曲线构造方法；新算法机制、算子、阶段和参数自适应方法；统计单位、主要终点、检验方法、多重校正和显著性阈值。仅下载原始数据、计算不改变语义的描述统计、校验哈希和发现缺口，不视为模型或方法变更。

未经批准时，证据包可以写 `PASS_EVIDENCE_AUDIT`，方法探针可以写 `PROBE_COMPLETED`，但机器合同必须保持 `HALT_*_AWAITING_USER_APPROVAL` 或 `DRAFT_METHOD_AWAITING_USER_APPROVAL`，`formal_search_allowed=false`，代码默认值、正式方法入口和实验合同不得改变。

## 审批单 MC-001：公开中国订单的体积到公斤转换

状态：`PENDING_USER_APPROVAL`。

原始事实：Figshare DOI `10.6084/m9.figshare.28113608.v1` 提供中国中部匿名零担城配企业10个高峰日、1222条订单。原始货量单位为立方米，只有1.0、1.5、2.0、2.5、3.0五档；数据没有实测公斤重量。论文案例给出源车辆容量7.2立方米；当前中国厢式电车合同的额定载重为1000公斤。

候选转换：`demand_kg = round(volume_m3 / 7.2m3 × 1000kg)`，得到139、208、278、347、417公斤。它保持每单占源车体积容量的比例，再映射成每单占目标车载重的同等比例。

性质：`CONSTRUCTED_CAPACITY_SHARE_SCENARIO_PROXY`。不得称为实测重量或中国货物平均密度；也不证明体积约束与重量约束等价。

可选决策：

1. 批准为正式基础情景。优点是完全可复现、与公开中国订单联合分布相连；风险是容量占比映射不是物理密度。
2. 仅批准为敏感性情景，正式主情景继续等待有重量字段的中国订单数据。科学最保守，但会继续阻断正式实例。
3. 否决，改用双容量模型（立方米和公斤同时约束）。物理含义更完整，但属于模型结构升级，需要车型货厢容积、货物重量或密度证据和新的算法改造。

关联证据：`data/ChinaInstances/china_order_attribute_calibration_v2_20260718/`。

当前机器处理：订单合同保持 `HALT_MODEL_TRANSFORMATION_AWAITING_USER_APPROVAL`；未改求解器、未生成正式实例、未运行算法搜索。

## 审批单 MC-002：E3–E7 机制暴露与统计显著性方案

状态：`PENDING_USER_APPROVAL`。

用户已批准目标：E3–E7 必须方向理想、效应量足够大且主要检验显著。尚未批准的是实现该目标的具体方法。

候选方法包括：以27个“地区×客户规模”为主要统计单位；每格三个互斥地图先聚合；每图至少五个共同种子；严格配对；五个主要检验族采用Holm校正；只按不含结果方向的方差规则扩样；为E3--E7分别设置责任错配、可移动充电量、非线性充电区、参与约束激活和动态多车场可行性的结果盲暴露门；E7增加“完整机制但碳盲”第五臂；算法采用六臂增量机制门。

这些内容当前只是 `data/ChinaInstances/china_e3_e7_significance_contract_v2_20260718.json` 中的候选设计，状态必须保持 `DRAFT_METHOD_AWAITING_USER_APPROVAL`。用户批准前，不得以此启动正式试验、修改正式算法或宣布统计合同已冻结。

待用户裁决的核心问题是：是否批准上述统计单位、Holm校正、最低种子数、五类暴露门、E7第五臂和算法六臂机制门作为一个整体；若只批准部分，须逐项记录。

## 审批单 MC-003：2025年2月默认展示日

状态：`PENDING_USER_APPROVAL`。

完整正式面板固定保留2025-02-01至2025-02-28，不因展示日选择删日。代理推荐C=2025-02-12，因为它是三地区碳强度与电价档冲突最强且日内碳差仍较大的共同日期，适合展示成本—碳权衡；但用户此前明确要求默认日期选择权由用户保留，所以旧`selected_by=user_authorized_F4_decision`记载不成立，已纠正。

其他选择是A=2025-02-16（三地区共同日内碳差最大，适合展示碳择时上限）、B=2025-02-10（回场后差最大但北京偏重）、D=各地区分别选最大日（只可作地区内图，不可跨区比较）。机器决策表保持`selected_option=null`，等待用户明确选择。

## 探索授权 EA-001：分机制算法创新候选池

状态：`APPROVED_FOR_EXPLORATION_ONLY`。

用户授权代理自主搜索和尝试针对每个机制的高性能开源/文献算子，也授权设计精细的自主创新算法或算子。用户保留最终批准权。该授权允许文献检索、许可证核对、独立目录中的原型、功能/活性/速度探针和候选排序；不允许未经批准合入正式ALNS、修改正式实验合同、启动正式E1--E7或写成论文创新结论。

五个主题、两轮研究要求、候选字段和探针纪律见`docs/handoff/alns_mechanism_innovation_exploration_contract_20260718.md`。每个候选后续需要独立审批编号。

### EA-001 / 主题1：混合车队、车型选择、SOC与非线性补能联合机制

状态：`EXPLORATION_ONLY_AWAITING_USER_APPROVAL`。

2026-07-18已按用户指定的EA-001和`academic-deep-research`两轮方法完成研究。独立证据包位于`docs/handoff/algorithm_exploration_20260718/fleet_charging/`，含`report.md`、`source_evidence.csv`、`candidates.json`、`decision.json`和`artifact_hashes.json`。正式solver、`winner.py`、E7、模型、单位、物理合同和正式实验均未修改；正式搜索评价次数为0。

Cycle 2逐一复核后保留五个待审批候选：`FC-C01`为Hiermann等的车型感知`Resize/RelocateAndResize`及联合路线—车型插入；`FC-C02`为Froger等的固定路线非线性充电精确标签oracle及Apache-2.0实现`frvcpy`；`FC-C03`为MIT许可PyVRP的异构车队局部搜索、缓存和粒度邻域工程参照；`FC-C04`为Wang等HEVRP-NL的逐车型路线评价、非线性补能评估、ReplacePath、VND与路线池架构；`FC-C05`为自研候选“车型—模式后悔修复 + 分层非线性补能oracle（VMR-NL）”。其中自研候选的新颖性尚未证明，必须经过独立文献审查和消融后才可形成论文主张。

隔离功能探针只证明`frvcpy`能在论文示例路线插入充电站、PyVRP能在微型异构车队实例选择大车型，不证明性能优于当前ALNS。EA-001下可继续的隔离探索顺序为`FC-C02 → FC-C05 → FC-C01 → FC-C04`；`FC-C03`主要作实现和外部基线参照，这一顺序不构成正式实施批准。G0闭合前只允许预登记的预算0/1/2/5微探针，完整评价、cheap filter、oracle调用、缓存命中和路线池求解必须分账。任何车型语义、SOC安全边界、非线性曲线、充电站可达性、目标函数或接受规则变化仍须另行审批。

### EA-001 / 主题3：时变碳、分时电价、充电调度与非线性充电

状态：`EXPLORATION_COMPLETED_AWAITING_USER_APPROVAL`。证据包位于`docs/handoff/algorithm_exploration_20260718/carbon_nonlinear_charging/`，判定保持`EXPLORATION_ONLY_AWAITING_USER_APPROVAL`。

两轮研究已核验Montoya--Froger--Liang非线性固定路线标签法、Lin时变电价VNS/TS、Lu时间依赖IVNS、Cheng滚动碳感知调度、cspy、PathWyse和SAP车场共享容量排程。关键许可证结论是：`cspy`为MIT；PathWyse为GPL-3.0-or-later，实施前须单独裁决许可证边界；Cheng第一作者仓库可核但没有LICENSE，禁止复制；SAP仓库为Apache-2.0但已于2026-07-16归档。

本主题提出自研候选`DUAL_ORACLE_CARBON_PRICE_CONFLICT_CHARGING`，并将两类识别分开：机制层在同一路线、车辆、总电量、曲线、桩容量和oracle下比较`JOINT_COST_CARBON`与`COST_ONLY_BLIND`；算法层保持正式评价目标不变，只开关碳冲突算子。E7碳盲臂必须使用同一滚动机制和oracle，只隐藏未来碳信号，不能用简单插入对精确调度。

本记录不构成正式实施批准。EA-001已允许在独立目录创建候选原型，并运行不影响正式求解器的预算0/1/2/5功能探针；时间/SOC离散、非线性资源扩展、碳价/碳目标语义、GPL组件接入以及任何正式接入仍须另建审批编号。建议的正式审批编号已预留为`EA-001-C3-P1/P2/L1/R1`；当前全部未批准。

### EA-001-T2：多车场合作责任重划与参与公平

状态：`EXPLORATION_ONLY_AWAITING_USER_APPROVAL`。

用户明确指定第二个算法探索主题，并要求按EA-001和`academic-deep-research`完成两轮研究，只探索、不修改正式solver、`winner.py`或E7。2026-07-18已完成Cycle 1候选地图与Cycle 2原论文、官方代码、许可证、算子细节和E3/E6接口核验，交付5个外部文献/开源候选和1个精细自研候选。

关键事实是：当前E6公平约束已经进入完整候选评价、局部搜索和修复后的可行性检查，不是纯事后筛选；但当前评分只按每个违规成员增加一个`BIG_M`，没有按公平赤字大小引导，也缺少公平专用的多步跨场链和路线池重组。Soriano等（2023）原文证实其公平修正插入会在重构阶段偏向未达到利润目标的车场；PyVRP v0.13.4的MIT源码证实真实SWAP-star、SwapTails和Exchange可作为高性能实现参照；路线池集合划分可把参与下界放入组合主问题，但ReSETP非零碳配额下的成员碳成本分配不完全路线可加，必须先做列语义审计。

探索包位于`docs/handoff/algorithm_exploration_20260718/collaboration_fairness/`，机器判决固定为`EXPLORATION_ONLY_AWAITING_USER_APPROVAL`、`formal_search_allowed=false`。EA-001已允许创建独立隔离原型并运行预算0/1/2/5功能探针，无须为每次探索重复请示；未经新的用户明确批准，不得合入正式ALNS、启动E3/E6机制门、改变模型/单位/参数或写成论文创新。建议探索顺序是：公平修正插入隔离原型、MIT署名的真实SWAP-star/SwapTails适配、路线列可加性审计；G0闭合前不得据此宣称性能优越。

### EA-001-T4：E7动态滚动重规划

状态：`EXPLORATION_ONLY_AWAITING_USER_APPROVAL`。

用户明确指定第四个算法探索主题，要求按EA-001和`academic-deep-research`完成两轮研究，并禁止读取当前E7中间结果、修改E7保护文件、`winner.py`或正式solver。2026-07-18已完成Cycle 1动态/在线VRP、滚动时域、路线冻结、regret/ejection、稳定性目标和dynamic ALNS候选地图，以及Cycle 2原论文、官方代码、许可证、算子API、响应时间和E7公开事件语义适配核验。

探索包位于`docs/handoff/algorithm_exploration_20260718/dynamic_replanning/`，含5个文献/开源候选和1个自研候选。关键边界是：Wang等（2024）的`O(1)`只指预处理后单个插入位置的时间窗可行性更新；PyVRP的warm start不等于硬冻结；dvrpsim是事件状态框架而非求解器；OR-Tools可锁在线路由中已经行驶的部分，但不原生覆盖ReSETP完整的非线性充电、公平和碳语义；RoutingBlocks只有源文件级MIT声明，根目录缺LICENSE文件。

EA-001下正在按四个彼此隔离的微探针推进：当前状态伪车场序列化回读、冻结前缀保持、有限深度regret-ejection的活性与完整评价计数、路线稳定性指标独立复算。原型只能位于独立目录，不得读取本轮E7中间结果。未经用户新的明确批准，不得把依赖接入正式仓库、修改正式目标/接受规则/预算、增加正式E7实验臂或合入正式ALNS。机器判决固定为`EXPLORATION_ONLY_AWAITING_USER_APPROVAL`、`formal_search_allowed=false`。

## 审批单 MC-004：同路径有向道路三矩阵候选方法

状态：`PENDING_USER_APPROVAL_AFTER_BLOCKERS_CLOSE`。

候选方法对每个有向起终点单独请求OSRM Route API，从同一条返回路线的逐段distance/duration annotation同时得到道路距离、路线总时间和`Σ(v²d)`；不使用欧氏倍数、统一速度或反向复制。

北京三个冻结客户的最小探针对六个方向全部请求成功，距离、时间和`Σ(v²d)`三组节点对均显示方向差异；7项测试、Ruff和18项产物哈希通过。证据包为`data/ChinaInstances/china_road_matrix_probe_v2_20260718/`，候选实现为`baselines/china_instances/build_china_directed_road_matrices_v2_20260718.py`。

当前不建议批准为正式方法：九城货车入口仍为0/9，探针未含车场和充电站；公共OSRM端点没有暴露可冻结的路由器版本和地图SHA；普通`driving` profile未证明是中国货运配置。候选判决保持`EVIDENCE_OR_PROBE_READY_ROAD_METHOD_AWAITING_USER_APPROVAL`、`formal_search_allowed=false`。在本地冻结OSM提取、路由器版本、货车profile与正式入口闭合后，应重新提交审批，而不是直接沿用公共API探针。

## 审批单 MC-005：九城客户配额的GDP-PPS方法

状态：`PENDING_USER_APPROVAL`。

2024年现价GDP已实现九城同年、同单位、官方来源9/9闭合；同批快递业务量只有6/9精确数值，未被混拼。候选A保留“小规模单核心、中规模双城、大规模全城市群”的空间层级，按GDP排序激活城市，再在激活城市内使用PPS和Hamilton/Hare最大余数法形成整数配额。九个指定规模已检查无城市配额随总规模增大而下降，但最大余数法一般仍存在Alabama paradox风险。

证据和27组候选配额位于`data/ChinaInstances/china_city_pps_calibration_v2_20260718/`，判决=`EVIDENCE_READY_METHOD_AWAITING_USER_APPROVAL`。现有客户位置合同没有被修改。

需用户一起裁决：是否接受GDP作为配送活动代理；是否接受成渝小规模核心由成都改成重庆、珠三角中规模双城由深圳—东莞改成深圳—广州；是否统一使用九城同批初步公报，还是另做九城最终年鉴刷新；是否接受重庆全域GDP与中心城区客户池的空间口径差异。

若批准候选A，成渝200客户格需要三个复本共348个重庆身份，现池305，须先补抓至少43个并重过27格充足性门；不得为绕过短缺修改配额。

## 审批单 MC-006：九城车场继续闭合与备选切换

状态：`PENDING_USER_APPROVAL`。

当前主候选的园区存在和仓储/配送运营属性均有9/9公开证据，但精确WGS84货车入口、外部配送货车通行合同和完整货运充电硬参数均为0/9。事实包`data/ChinaInstances/china_depot_site_evidence_v2_20260718/`判决=`EVIDENCE_READY_SITE_SELECTION_OR_ASSUMPTION_AWAITING_USER_APPROVAL`，没有修改现有manifest。

候选动作一是保留九个当前普通商业园区，由代理在地图/浏览器中逐城定位货车入口，并在公开资料不足时请求用户按`proposed_manifest_patch.json`给出的最小步骤人工截图或联系园区。地图入口只能作为坐标证据，不能自动证明外部货车准入、时段和预约。

候选动作二是批准进一步调查深圳华南物流园和重庆京东亚洲一号。两者公开资料的货运充电证据强于当前主候选，但批准调查不等于批准替换；替换前还需比较普通商业属性、敏感性、入口、货车通行、充电硬参数、电价合同和与客户池的道路关系。

候选动作三是在实际现场数据持续不可得时，使用用户已允许讨论的“规划许可视为已投运”情景。该动作仍需逐场审批，并明确标注`ASSUMED_COMMISSIONED_SCENARIO_NOT_OBSERVED_OPERATION`；桩位不得自动等于桩数或枪数，功率仍须有独立产品/项目来源。

## 后续登记格式

每项新增审批必须记录：编号、原值/原语义、拟变更值/语义、来源链接与本地快照、转换公式与单位检查、影响的公式/代码/实验、替代方案、独立核验结果、用户原话或明确选择、批准日期、实施提交、回归测试和可回滚点。
