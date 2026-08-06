# D4 中国81算例输入来源与论文措辞对抗性评审

状态：`D4_INSTANCE_PROVENANCE_COMPLETE`

## 结论先行

**FACT。** 论断 I 的事实核心成立：China81 的关键输入中确有大量构造项。按本任务规定的五类重新逐项登记，44 类输入中，`构造` 26 类、`公开发布` 9 类、`文献迁移` 4 类、`未登记` 5 类、`观测` 0 类。尤其车队规模与配比、车场和公共站设备能力、客户公斤需求、路由距离/时间、客户—车场归属和动态订单流均不是China81企业现场观测。直接证据是 `baselines/china_e3_e7/e3e6_gates_01_20260729/gate1_d2a/fleet_caps.csv` 的 `fleet_parameter_class=CONSTRUCTED_DEMAND_TIME_WINDOW_ROAD_SCENARIO` 和 `charger_parameter_class=CONSTRUCTED_SCENARIO_NOT_OBSERVED_SITE_CONTRACT`，以及 `provenance_ledger.json` 的逐项来源链。

**FACT。** 论断 I 所说“论文把81个中国算例呈现为真实业务算例”不符合当前全文的主导措辞。摘要明确写“中国三大城市群仿真算例”（`docs/paper_v2/paper_main.tex:144`），英文摘要写“simulations”（`:161`），引言写“仿真实验”（`:259`），实验设计再次写“设计仿真实验”（`:922`），订单被明确称为“合成订单（非企业实测订单）”（`:931`），电价表注明确写“构造情景，非命名车场合同观测”（`:1030`），碳强度明确写为模型投影而非实测（`:1043-1046`），历史归属明确写为构造（`:1381-1383,1535`）。全文检索没有“真实业务数据”或将81个算例称为企业订单记录的句子。

**INFERENCE。** 论断 I 因而只能判为**部分成立**：第一句“大量关键输入构造而非观测”成立；第二句所设条件只在若干局部措辞上触发，而不是全文把算例冒充为企业实测。真正的高风险点是12处可核验的来源强度或版本错配，其中最重的是订单规则已过期（`:931-934`）、EV迎风面积与代码不一致（`:983`）、碳列映射写成三条而运行时实际使用六列（`:1040-1042`），以及结语“81个自有算例”（`:1545`）脱离“仿真”限定后存在歧义。逐项见 `wording_gaps.json`。

**VERDICT。** 不支持把当前稿件定性为“将81个构造算例整体伪装成真实业务数据”，也不支持在未经历审稿的情况下把问题直接判成“致命”。支持的对抗性结论是：**China81 是以公开地理/政策/车型锚点、外部案例迁移和大量构造规则组成的混合仿真算例集；当前稿件总体承认其仿真属性，但局部存在来源抬高、规则陈旧和运行时错配，足以触发审稿人的可复现性与外部效度追问。**

## 一、输入来源台账

### 1.1 分类口径

`观测`仅指直接来自China81对应企业、车场、车辆或运营日的测量/业务记录；`公开发布`指直接采用的政府、厂商、OSM或公开数据集字段；`构造`指研究者抽样、转换、路由、映射、设档或公式派生的场景输入；`文献迁移`指把外部论文或公开案例中的经验字段/参数迁入China81；`未登记`指实现中有值，但现有材料没有可回放的来源或转换依据。按此口径，外部匿名企业时间窗即使在源案例中是观测，迁入另行选择的OSM客户后仍记为`文献迁移`。

完整机器可读台账见 `provenance_ledger.json`。下表逐项列出44类输入及核心证据；每项更完整的字段与边界在该JSON的 `evidence`、`note` 中。

| ID | 输入 | 分类 | 核心可核验证据 |
|---|---|---|---|
| P01 | 规模梯度、城市群分层、三复本结构 | 构造 | `paper_main.tex:923-927`；位置权威 `decision.json: instances=81, assignment_rows=5805` |
| P02 | 客户坐标及其作为客户的身份 | 构造 | 位置 `assignments.csv: osm_id,latitude,longitude,location_seed`；构造器 `build_china81_customer_location_assignments_v2_20260718.py:55-57,103-124` |
| P03 | 客户城市配额与实例内分配 | 构造 | `assignments.csv: city_quota,city_selection_rank,replicate`；同构造器 `:96-108` |
| P04 | 客户需求量kg | 构造 | `orders.csv: demand_classification=CONSTRUCTED_CAPACITY_SHARE_SCENARIO_PROXY`；标定器 `:221-235,310-316` |
| P05 | 服务时长 | 文献迁移 | `orders.csv: service_classification=PUBLISHED_CASE_PARAMETER_NOT_OBSERVED_STOP_DURATION`；构造器 `:155,166-167` |
| P06 | 交付时间窗 | 文献迁移 | 订单 `metadata.json: sampling=complete empirical rows with replacement`；`orders.csv: source_order_uid,window_classification` |
| P07 | 车场名称/设施身份 | 公开发布 | `facilities.csv: depot_name,depot_source` |
| P08 | 车场模型坐标 | 构造 | `facilities.csv: depot_point_semantics=SCENARIO_ROAD_ACCESS_POINT_NOT_OBSERVED_TRUCK_GATE` |
| P09 | 车场数量与客户同城归属 | 构造 | `china81.py:355-375`；`depot_field_investigation.json: literal_registered_depot_column_found=false` |
| P10 | 公共站身份与坐标 | 公开发布 | `facilities.csv: station_identity,station_source,station_source_class` |
| P11 | 有向道路距离矩阵 | 构造 | 道路 `metadata.json: router,ordered_pairs=1578948,euclidean_or_symmetry_fallback=false` |
| P12 | 有向行驶时间矩阵 | 构造 | 道路 `metadata.json: profiles=[cv,ev],cache_reuse_semantics` |
| P13 | `sum(v^2d)`矩阵 | 构造 | 道路 `metadata.json: same_route_distance_duration_sum_v2d=true` |
| P14 | 燃油车数量 | 构造 | `fleet_caps.csv: base_all_cv_routes_Rd,num_cv,fleet_parameter_class` |
| P15 | 电动车数量与CV/EV配比 | 构造 | `fleet_caps.csv: main_reserve_factor,num_cv,num_ev`；车队构造器 `:214-223` |
| P16 | 车队储备因子敏感性档 | 构造 | `fleet_caps.csv: sensitivity_json`（1.10/1.25/1.50） |
| P17 | 车场桩数/功率 | 构造 | `fleet_caps.csv: 2,22.0,charger_parameter_class=CONSTRUCTED_SCENARIO_NOT_OBSERVED_SITE_CONTRACT` |
| P18 | 公共站桩数/功率 | 构造 | `facilities.csv: 1,60.0,station_parameter_class=UNIFORM_PREDECLARED_SCENARIO_PROXY` |
| P19 | 分时电价表值 | 公开发布 | `china_2025_02_tariff_register_v2.json: sources,one_to_ten_kv_candidate_rows`；`tariff_source_hash_register.csv: status=PASS` |
| P20 | 车场合同类别与城市—价区映射 | 构造 | 电价登记 `formal_row_rule,f3_scenario_rule`；运行日历 `tariff_row_class=ONE_TO_TEN_KV_SINGLE_PART_SCENARIO_ROW` |
| P21 | 公共充电服务费0.40元/kWh | 未登记 | 运行日历 `service_fee_class=UNIFORM_SCENARIO_PROXY_NOT_MARKET_OBSERVATION`；旧审计 `report.md:563-574` |
| P22 | Li等S1-2025碳强度源序列 | 公开发布 | 旧审计 `report.md:329-339`（Figshare DOI和原始文件哈希）；运行日历 `carbon_source_column` |
| P23 | 省级小时值到九城48槽日历 | 文献迁移 | 旧审计 `report.md:331-339`；运行权威 `decision.json: calendar_rows=12096,city_count=9` |
| P24 | 预测碳强度=核算碳强度 | 构造 | `china81.py:805-817`；`paper_main.tex:1043-1046` |
| P25 | CV质量、载重、外廓 | 公开发布 | `china_vehicle_parameter_sources_20260718/source_evidence.csv: JAC-WLING-K7-CV-OFFICIAL`；`china81.py:638-658` |
| P26 | EV质量、载重、电池 | 公开发布 | `V04_foton_aumark_es1.md: 可复核字段`；`china81.py:660-685` |
| P27 | EV高度2.480 m | 构造 | `china81.py:666-671,682: HEIGHT_ASSUMED_SYMMETRIC_WITH_CV_FIELD_INCOMPLETE` |
| P28 | 迎风面积投影因子0.85 | 未登记 | `china81.py:644,655,671,683`；旧审计 `report.md:69-80` |
| P29 | 空气阻力系数0.45 | 未登记 | `china81.py:646,656,673,684`；旧审计 `report.md:82-93` |
| P30 | 滚阻、空气密度、发动机和电驱系数 | 文献迁移 | `prices.py:9-41`（Goeke 2015、Demir 2012逐参数登记） |
| P31 | EV初始电量0 kWh | 未登记 | `china81.py:893-895`；旧台账 `ledger.csv:L08` |
| P32 | NL90分段充电曲线 | 未登记 | `china81.py:20,915-917`；`paper_main.tex:938`；无ES1实测/具页码来源登记 |
| P33 | CV/EV非能源里程费率 | 构造 | `china81.py:648,675,914`；旧审计 `report.md:550-561` |
| P34 | 京津冀、广东、四川柴油价 | 公开发布 | `diesel_price_2025_02_12_source_register.csv: reviewed_source_strength=DIRECT_OFFICIAL_*` |
| P35 | 重庆柴油价7.50元/L | 构造 | 同登记 `reviewed_source_strength=DERIVED_FROM_OFFICIAL_NDRC_PER_TON_AND_OFFICIAL_LOCAL_ADJACENT_RETAIL_TABLES` |
| P36 | 柴油排放因子 | 公开发布 | `china81.py:908`；`paper_main.tex:1033`；旧台账 `ledger.csv:L27` |
| P37 | 碳价主值/低值 | 公开发布 | `china81.py:906-907`；`paper_main.tex:1001-1002` |
| P38 | 派遣费、占用费、单位货量收入 | 构造 | `china81.py:909-912`；`paper_main.tex:1033-1035` |
| P39 | 运营时域与正式日期 | 构造 | `china81.py:30-32`；运行权威 `decision.json: scenario_date=2025-02-12` |
| P40 | 基础客户承包商/归属车场 | 构造 | `china81.py:355-375`；`depot_field_investigation.json: loader_derivation` |
| P41 | E3散乱历史客户归属 | 构造 | `paper_main.tex:1380-1383,1535` |
| P42 | 动态事件类型、比例、到达时刻 | 构造 | `dynamic.py:32-65,154-185`；冻结流 `stream_seed1.json: source=synthetic_overlay` |
| P43 | 动态新增订单属性 | 构造 | `dynamic.py:196-240`；`mechanism_foundation.py:156-197` |
| P44 | 跨场摩擦与参与阈值 | 构造 | `china81.py:911-913`；旧审计 `report.md:576-580` |

### 1.2 两个总账层面的发现

**FACT。** 用户指定线索 `docs/handoff/memory/instance-lineage.md` 当前只登记L-main v3：其“Formal default”是 `models/data_bundle/generated_instances/L-main/`，9个threeshift算例（`:5-18`），全文没有China81来源总表。因此它不能作为China81的总体来源证明；China81目前要靠位置、订单、设施、道路、运行参数和车队五套分散权威包拼接。

**FACT。** `solver/src/setp_solver/china81.py:53-56` 默认仍指向 `china81_finite_fleet_authority_v1_20260723`，而用户线索来自后续gate副本。`data/ChinaInstances/china81_finite_fleet_authority_v2_20260731/report.md` 记录v1/v2 `fleet_caps.csv` 逐行全等、总CV=1040、EV=309，且两份CSV当前SHA-256均为 `48fcf934e480504d22981e850e24ce0daa7ff11b2f73d4f806b6396cd9fcd367`。因此默认版本号落后不改变本次来源判定：两版都明确是构造车队。

## 二、论文实际措辞逐处核对

### 2.1 摘要与引言

| 行号 | 原句 | 与台账关系 |
|---|---|---|
| 144 | “在标准算例和中国三大城市群仿真算例上比较算法的求解质量” | **相符。** 明确为仿真，没有声称企业观测。 |
| 161 | “public benchmarks and simulations of three Chinese urban agglomerations” | **相符。** 英文摘要同样限定为simulations。 |
| 259 | “对仿真实验进行求解分析” | **相符。** 引言未把China81写成现场数据。 |
| 271 | “设置算法对比以及……三组正式机制实验” | **中性。** “正式”修饰实验地位，不等于数据为实测；来源仍由`:922-938`界定。 |

### 2.2 数值实验设计、表注与图表标题

| 行号 | 原句/大意 | 判断 |
|---|---|---|
| 922-927 | “依据现实情况和相关文献设计仿真实验”“本文构建的……共81个算例” | **相符。** 自建仿真集的定位准确。 |
| 928 | “车场与客户位置基于真实设施点位构建” | **强于来源。** 客户身份是OSM池固定种子抽样，车场模型点是非观测道路接入点；见gap 1。 |
| 929 | “OSM……和OSRM……真实道路计算” | **强于来源。** 可称路网路由计算，不可让人理解为车辆实测；见gap 2。 |
| 930 | “运营时域为本地时间06:00--22:00” | **中性但属构造。** `china81.py:30-32`登记该研究时域，没有把它称作企业班次观测。 |
| 931-934 | “合成订单（非企业实测）”及三段需求、8/12/18 min、30 min网格 | **来源总类相符、具体规则不符。** 当前为五档公斤代理、五档服务时长和外部案例连续时间窗联合重采样；见gap 3。 |
| 936-937 | 车型参数为国内在售厢式货车官方数据，物理系数文献迁移 | **部分不符。** EV为栏板；官方字段、构造高度、未登记风阻/投影因子和文献系数不能打包；见gap 4。 |
| 938 | NL90分段曲线 | **规则与代码相符、来源未登记。** 见gap 5。 |
| 940-948 | 反复称“仿真算例”，并区分全81判断与机制展示例 | **相符。** 没有业务数据暗示。 |
| 949、954 | “仿真算例的节点信息”“仿真算例节点信息表” | **相符。** 标题继续保持仿真限定。 |
| 983 | EV迎风面积6.08 | **不符。** 当前代码CV/EV均4.6376；见gap 6。 |
| 991 | 表注把质量/载重/电池称官方，把风阻/投影/能耗合称公开代理与文献迁移 | **部分不符。** 风阻和0.85因子无可回放来源；见gap 7。 |
| 994 | “参考现实数据与相关文献设置以下参数” | **强于来源。** 后续混有构造和未登记项；见gap 8。 |
| 995-996 | 九城柴油价均称城市发改部门公布 | **部分不符。** 重庆7.50为官方材料推导情景；见gap 9。 |
| 1014、1030 | 标题称“电能价格情景”，表注明确“构造情景，非命名车场合同观测” | **相符且充分。** 这是当前最清楚的来源边界表述。 |
| 1036 | 公共站60 kW、车场22 kW | **数值相符、来源未披露。** 两者都是统一预设能力；见gap 10。 |
| 1038-1046 | 碳强度称S1模型投影、非官方实测，预测=核算 | **来源类型相符；映射不符。** `:1040-1042`说三区各取核心省级序列，但运行时逐城用六列；见gap 11。 |
| 1052、1054 | “典型日电网碳强度曲线”，并注明同一预测/核算值 | **相符。** 投影边界已在紧邻正文`:1043-1046`明确。 |
| 1059、1074 | “五个种子构造解”“仿真实验最终路径表” | **相符。** 明确是构造解/仿真。 |
| 1270、1276、1296 | “全部81个算例”“中国三大城市群算例集”及运行来源表注 | **中性且可回溯。** 来源类型已由本节开头限定为仿真；表注给出结果文件，不等于输入来源总账。 |
| 1380-1383、1392 | 现实承包关系作动机，明确“采用Soriano……构造历史客户组合” | **相符。** 动机与构造输入分开写明。 |

### 2.3 讨论与结语

| 行号 | 原句 | 判断 |
|---|---|---|
| 1535-1536 | “客户责任采用构造的散乱历史归属……后续可用企业订单流……扩展实验” | **相符。** 明确当前没有企业订单流，并指出扩展边界。 |
| 1545 | “通过公开标准算例和中国81个自有算例验证……” | **有歧义。** “自有”可理解为作者自建，也可能被读成自有业务数据；结语应保留“本文构建的仿真算例”限定，见gap 12。 |

`wording_gaps.json` 只收录强于来源、版本不符或来源边界缺失的12项；相符措辞没有混入gap清单。

## 三、同类论文如何交代构造算例

### 3.1 目标期刊直接先例一：陈雨蝶等（2025）

**FACT（来源说明）。** 《双碳背景下复杂冷链物流模型及求解算法》，《系统工程理论与实践》网络首发稿，DOI `10.12011/SETP2024-2027`。PDF第11页在“实验设计”中先写“依据现实情况和相关文献设计仿真实验”，随后明确坐标参考Solomon R类生成方式、客户位置随机分布于0—100范围、时间窗服从离散均匀分布。本地原文：`/Users/zhouleixishu/Zotero/storage/AYDB6KXP/陈雨蝶 等 _ 2025 _ 双碳背景下复杂冷链物流模型及求解算法.pdf`，PDF p.11。

**FACT（局限说明）。** 同文印刷页21（本地PDF p.22）明确承认研究基于仿真实验，实际物流还受天气、拥堵和突发订单等因素影响，并提出未来结合实际运营数据验证；同时承认碳价、需求等因素被简化。这个先例的处理方式是：在设计处给出随机生成规则，在讨论处把“没有实际运营数据”写成外部效度边界。

### 3.2 目标期刊直接先例二：饶卫振等（2022）

**FACT（混合来源分层）。** 《考虑企业服务质量差异的协作配送问题及成本分摊方法研究》，《系统工程理论与实践》42(10):2721-2739，DOI `10.12011/SETP2021-3282`。第2731页明确写四家企业客户“随机分布在边长为70 km×70 km的正方形区域内”，客户需求量为随机数；同文第2733页又把顺丰、中通、圆通、申通的服务质量指标称为根据实际数据测算，第2737页提出未来加入更多现实客观因素。本地原文：`/Users/zhouleixishu/Zotero/storage/RHSBVJ6Z/饶卫振 等 _ 2022 _ 考虑企业服务质量差异的协作配送问题及成本分摊方法研究.pdf`，期刊pp.2731、2733、2737。

**INFERENCE。** 这个先例与China81最接近：同一论文可以同时有真实/公开校准指标和随机路由输入，关键是逐层说明，不能因为某些服务指标来自实际数据，就把客户坐标、需求和路径算例整体称为真实业务案例。

### 3.3 同类国际先例：Soriano等（2023）

**FACT（明确人工生成）。** Soriano, Gansterer and Hartl, “The multi-depot vehicle routing problem with profit fairness”, *International Journal of Production Economics* 255 (2023) 108669。第7页直接写“artificial MDVRP-PF instances are generated”，并说明客户位置分为clustered/uniform、初始收入分为balanced/unbalanced，每个组合生成2/3/4车场和100/150/200客户三档；同页说明全部生成算例可在其数据仓库取得。本地原文：`/Users/zhouleixishu/Zotero/storage/PLSR8GG4/Soriano 等 _ 2023 _ The multi-depot vehicle routing problem with profit fairness.pdf`，PDF p.7。

**FACT（结论边界）。** 同文第11页把结论限定为“newly generated set of instances”上的配置依赖效应，并给出Data availability标识 `10.17632/rhgk26ngs8.2`；未来方向是更丰富的路由变体和公平指标，而非把生成算例改称实地案例。本地原文同上，PDF p.11。

### 3.4 目标期刊的较弱披露先例：饶卫振等（2019）

**FACT。** 《一种求解协作配送成本分摊问题核仁解的近似迭代算法》，《系统工程理论与实践》39(6):1517-1534，DOI `10.12011/1000-6788-2018-1668-18`。第1528页写“基于某城市4个牛奶配送企业……的配送数据，设计协作配送问题算例如下”，随后给出80个客户和4个中心的数值坐标、统一10箱需求、100箱车容量和10元/km，但没有在该页登记企业、坐标文件或观测时间。本地原文：`/Users/zhouleixishu/Zotero/storage/W96R3AUG/饶卫振 等 _ 2019 _ 一种求解协作配送成本分摊问题核仁解的近似迭代算法.pdf`，期刊p.1528。

**INFERENCE。** 该文证明匿名数值案例曾被目标期刊接收，但其来源透明度弱于陈雨蝶2025和饶卫振2022；它不能为“真实业务”扩写提供证据，只能说明目标期刊并不要求每篇算法/机制论文都拥有可公开企业微观数据。

### 3.5 对本文投稿资格的回答

**VERDICT。** 如实交代“构造情景”后，本文仍可投《系统工程理论与实践》。构造算例不是该期刊的排除条件：陈雨蝶等（2025）在目标期刊明确使用随机客户与随机时间窗仿真；饶卫振等（2022）在目标期刊明确使用随机客户位置与随机需求；Soriano等（2023）在同类高水平生产运作期刊明确发布人工生成算例。三篇的共同最低要求是：设计处写清生成规则和哪些字段来自现实/公开锚点，结果处不把情景效应外推成企业观测事实，讨论处说明未覆盖的现实扰动或外部效度边界。

对ReSETP而言，投稿障碍不是“使用构造算例”本身，而是当前 `paper_main.tex:931-934,983,1040-1042` 与运行时权威不一致，以及`:928-929,991,994,995-996,1036,1545`的来源措辞强于可核验证据。这个判断分别由 `provenance_ledger.json` 和 `wording_gaps.json` 闭合。

## 停止条件

三部分均已完成；只在 `docs/handoff/diagnosis_20260802/d4_instances/` 新建D4交付物。未改代码、未改TeX、未改 `baselines/` 或 `data/`。终态为 `D4_INSTANCE_PROVENANCE_COMPLETE`。
