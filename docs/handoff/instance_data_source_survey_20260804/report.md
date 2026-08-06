# T2-INSTANCE-SOURCE：中国城配 VRP 算例数据源调查与现有源质量评估

日期：2026-08-04  
模式：只读调查；未修改既有文件，未生成算例，未运行求解器或实验。  
口径：本文不作数据源取舍，条目顺序仅按“当前源—中国新增源—标准/国际源—仓库渠道”组织，不表示优先关系。`search_evaluations=0`。

## 摘要结论

**FACT—合法使用。** Figshare v1 对数据集明确给出 CC BY 4.0；在履行署名等许可条件的前提下，期刊名称并不是该数据能否复用的法律开关。PLOS ONE 的官方编辑口径是按科学有效性、方法和伦理标准审查，而不是按“感知重要性”筛选；这既不能反向证明原始企业数据失实，也不能替代采集协议、城市、日期和质量控制记录。[PLOS ONE 期刊说明](https://journals.plos.org/plosone/s/journal-information)；[Figshare 数据页](https://figshare.com/articles/dataset/Plos_ONE_Supplementary_documents/28113608)

**FACT—经验来源。** Zhang（2025）把案例称为中国中部一家匿名零担城市物流企业在一个片区、连续 10 个高峰日的真实历史数据。Figshare 的十个日文件合计 1,222 单。论文和数据页没有披露企业、城市、具体日历日期、抽样框、导出接口、清洗流程、缺失处理或质量控制方案；因此匿名性与采集说明不足限制的是来源可核验性和外推范围，不是否定许可。

**FACT—字段语义。** 源文件中的体积、取货/交付时间窗和订单/车辆平面位置属于发布数据字段；本项目把体积按 `round(volume/7.2*1000)` 转为公斤，这是经批准的 capacity-share proxy，不是实测重量。服务时长按 `volume*0.1 h/m3*60` 得到，是论文案例参数的确定性换算，不是逐站实测时长。当前模型把交付窗作为硬约束，但 Zhang（2025）原模型以迟到罚金处理时间窗，并把硬时间窗列为后续研究方向。

**FACT—生成后分布。** `orders.csv` 有 5,805 行订单。需求只有 139/208/278/347/417 kg 五个质量点，均值 268.605 kg、中位数 278 kg；交付窗起点范围 11:07:47–17:52:06，中位 13:33:40，5%–95% 为 11:41:06–17:03:38；窗宽范围 30.016–59.975 min，中位 45.833 min；服务时长只有 6/9/12/15/18 min，中位 12 min。由此，提示中的“11:14–18:06、中位宽度 56 min”不等于当前文件的实际统计量。

**INFERENCE—可支持的论文措辞。** 当前证据支持“九城客户位置上的订单属性由一家中国中部匿名企业历史订单的交付窗与体积分布，经冻结的联合经验重采样及已批准代理换算构造”。它不支持“九个城市的实测订单”“实测公斤需求”“实测服务时长”，也不支持把当前硬时间窗语义说成原论文已验证的硬约束。把 proxy、联合重采样和 GIS 迁移说清楚后，“基于真实中国订单属性的构造算例”仍是可追溯表述；省略这些变换而写“真实中国订单”会扩大证据范围。

## 第一部分：现有数据源评估

### 1. Zhang（2025）全文逐页核读

论文：[A collaborative freight delivery problem with time windows under a crowdsourcing environment](https://doi.org/10.1371/journal.pone.0318432)，PLOS ONE 20(2):e0318432，官方 PDF 共 21 页。页码以下均为 PDF 页码。

| PDF 页 | 本页内容与数据证据 |
|---:|---|
| 1 | 题名、摘要、开放许可。摘要介绍在线协同货运配送与算例验证；未给采集协议。 |
| 2 | 引言说明 O2O 平台的一般信息流；属于问题背景，不是本数据的采集方法。 |
| 3 | 引言/文献综述继续；列举订单可能含下单时间、取送地址、时间窗、体积或重量，仍非本案例的字段审计。 |
| 4 | 文献综述与研究贡献；无新增来源说明。 |
| 5 | 问题描述与符号；订单具有取货点、送达点、体积和时间窗。 |
| 6 | 在线策略与系统状态；无数据采集说明。 |
| 7 | 模型定义；无企业或日期信息。 |
| 8 | 数学模型；时间窗进入成本/约束结构。 |
| 9 | 参数定义，装卸时间与订单体积有关；没有声称逐站实测服务时长。 |
| 10 | 约束与模型解释；无来源信息。 |
| 11 | 约束与模型解释；无来源信息。 |
| 12 | 求解模型；无来源信息。 |
| 13 | 求解模型；无来源信息。 |
| 14 | 求解模型；无来源信息。 |
| 15 | IPGA 算法；无来源信息。 |
| 16 | IPGA/SA 算法；无来源信息。 |
| 17 | 数值实验参数；出现 7.2 m³ 车辆容量、30 km/h、90 RMB 固定成本、7.5 RMB/km、0.1 h/m³ 等案例参数。 |
| 18 | 真实案例的核心来源页：Z 企业是一家使用众包货运平台、服务批发市场商户的中国中部物流企业，业务含干线、城市物流、冷链；研究选取一个配送片区连续 10 个高峰日的零担城配历史数据。作者称数据能反映该片区日常订单到达与车辆班次变化。 |
| 19 | 案例结果和结论。作者的限制声明包括：现阶段只考虑固定罚金或空车场情形；平台自有车辆与硬时间窗留待未来研究。 |
| 20 | 参考文献；无新增数据说明。 |
| 21 | 参考文献；无新增数据说明。 |

采集来源、方式与代表性可拆为以下事实：

| 项目 | 核读结果 | 证据 |
|---|---|---|
| 采集对象 | 中国中部匿名“Z 企业”；零担城市物流；一个配送片区；批发市场商户；企业使用众包货运平台 | Zhang PDF p.18 |
| 时间跨度 | 连续 10 个高峰日；未披露年月日，也未定义“高峰日”的抽样规则 | Zhang PDF p.18；Figshare 描述 |
| 采集方式 | 论文没有披露 API、数据库导出、人工录入、问卷、设备采集、清洗或缺失处理流程 | Zhang PDF pp.1–21 全文核读 |
| 订单字段 | 订单号、呼入时间、客户/商户平面坐标、取货早/晚、交付早/晚、距离、耗时、体积、装卸时间 | Figshare Day 1–10 工作簿表头 |
| 车辆字段 | 车辆号、更新时刻、车辆平面坐标 | Figshare Day 1–10 `vehicle` 工作表 |
| 代表性说明 | 作者只称该样本反映该企业/片区的日常订单到达和车辆班次变化；未给全国、城市群或行业代表性抽样论证 | Zhang PDF p.18 |
| 自身局限 | 固定罚金或空车场；平台自有车辆和硬时间窗未纳入，列为后续方向 | Zhang PDF p.19 |

### 2. Figshare 数据集核对

数据集：[Plos ONE Supplementary documents](https://doi.org/10.6084/m9.figshare.28113608.v1)，版本 1，发布/修改日期均为 2024-12-31，许可 CC BY 4.0，描述为“高峰期 10 天数据和论文插图”。API 在 2026-08-04 返回 23 个文件。

文件清单为：`Data Description.xlsx`；`Day 1.xlsx` 至 `Day 10.xlsx`；`Fig 1. The Dynamism of the Online Strategy.pdf`；`Fig 2. An Example of the CFDRP.pdf`；`Fig 3. The Process of IPGA.pdf`；`Fig 4. Chromosome Representation at First Stage.pdf`；`Fig 5. Crossover Operation of PDDV.pdf`；`Fig 6. Crossover Operation of PDSV.pdf`；`Fig 7. Crossover Operation of EUV.pdf`；`Fig 8. Crossover Operation of IPDV.pdf`；`Fig 9. Mutation Operation.pdf`；`Fig 10. The Process of SA.pdf`；`Fig 11. Computational Enhancements with IPGA.png`；`Fig 11. Computational Enhancements with IPGA.py`。

仓库本地目录 `data/ChinaInstances/open_sources_20260717/figshare_28113608/` 保存了 11 个数据工作簿，即说明文件和 Day 1–10。十天订单数依次为 79、159、82、167、77、163、76、168、82、169，合计 1,222。`Data Description.xlsx` 给出规划时段 08:00–11:00、13:00–19:00，时间以 08:00 为零点；交付处理窗 1 h、取货处理窗 1.5 h；以及 7.2 m³、30 km/h、90 RMB、7.5 RMB/km、0.1 h/m³ 五项案例参数。

数据说明文件存在，但它是参数表，不是完整数据字典：没有坐标系/投影、城市、具体日期、企业、字段来源链、缺失编码、异常处理、质量控制或版本变更说明。Figshare 的 CC BY 4.0 覆盖数据集；文章和数据许可不等于对匿名企业来源作独立认证。

仓库可追溯证据：

- `docs/handoff/china_order_attribute_contract_v2_20260718.md:11-31`：来源、匿名边界、proxy、服务时长与联合抽样。
- `data/ChinaInstances/china_order_attribute_contract_v2_20260718.json:46-96`：机器合同、许可、1222 行、五档映射和服务公式。
- `data/ChinaInstances/china_order_attribute_calibration_v2_20260718/report.md:7-19`：工作簿审计与源分布。
- `docs/handoff/model_change_approval_register_20260718.md:181-197`：MC-001 事实、选项和批准记录。
- `docs/handoff/model_change_approval_register_20260718.md:197`：联合重采样与服务公式的补充终裁。

### 3. `orders.csv` 描述统计

输入：`data/ChinaInstances/china81_order_attributes_gis_v2_20260723/orders.csv`。共 81 个实例、5,805 行订单；9 个客户规模各有 9 个实例。完整原始统计输出见 `descriptive_stats.csv`，含每组的 n/min/p05/p25/median/mean/p75/p95/max/std、五档频数和源行复用统计。

总体统计：

| 指标 | n | min | p05 | p25 | median | mean | p75 | p95 | max | std |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| demand_kg | 5805 | 139 | 139 | 208 | 278 | 268.605 | 347 | 417 | 417 | 97.258 |
| 交付窗起点/min after midnight | 5805 | 667.784 | 701.110 | 758.375 | 813.662 | 839.405 | 930.636 | 1023.627 | 1072.101 | 101.630 |
| 交付窗宽/min | 5805 | 30.016 | 31.492 | 38.281 | 45.833 | 45.316 | 52.359 | 58.406 | 59.975 | 8.443 |
| 服务时长/min | 5805 | 6 | 6 | 9 | 12 | 11.603 | 15 | 18 | 18 | 4.199 |

时间窗起点换算为钟表时间：min 11:07:47、p05 11:41:06、p25 12:38:23、median 13:33:40、mean 13:59:24、p75 15:30:38、p95 17:03:38、max 17:52:06。

五档频数：

| source_volume_m3 | demand_kg | service_min | count | share |
|---:|---:|---:|---:|---:|
| 1.0 | 139 | 6 | 1334 | 0.229802 |
| 1.5 | 208 | 9 | 1166 | 0.200861 |
| 2.0 | 278 | 12 | 1191 | 0.205168 |
| 2.5 | 347 | 15 | 1162 | 0.200172 |
| 3.0 | 417 | 18 | 952 | 0.163997 |

按客户规模统计；每格为 mean / median：

| 客户数 | 订单行数 | demand_kg | 窗起点 | 窗宽/min | 服务/min |
|---:|---:|---:|---|---:|---:|
| 10 | 90 | 266.267 / 278 | 13:52:07 / 13:31:44 | 43.766 / 43.282 | 11.500 / 12 |
| 15 | 135 | 271.570 / 278 | 13:54:01 / 13:24:42 | 44.776 / 44.988 | 11.733 / 12 |
| 20 | 180 | 265.072 / 278 | 14:09:40 / 13:46:36 | 45.344 / 45.598 | 11.450 / 12 |
| 25 | 225 | 266.378 / 278 | 13:51:57 / 13:23:24 | 45.331 / 46.332 | 11.507 / 12 |
| 50 | 450 | 266.373 / 278 | 13:57:33 / 13:28:50 | 45.107 / 45.378 | 11.507 / 12 |
| 75 | 675 | 268.427 / 278 | 14:00:38 / 13:32:54 | 45.109 / 45.649 | 11.596 / 12 |
| 100 | 900 | 265.900 / 278 | 14:00:49 / 13:33:36 | 45.309 / 45.793 | 11.487 / 12 |
| 150 | 1350 | 266.369 / 278 | 14:01:18 / 13:38:46 | 45.538 / 46.026 | 11.507 / 12 |
| 200 | 1800 | 272.784 / 278 | 13:57:57 / 13:32:58 | 45.397 / 45.926 | 11.783 / 12 |

**FACT。** 5,805 行使用了 1,222 个源订单中的 1,211 个，单个源行最多复用 12 次；这是有放回整行抽样的预期结果。各规模的需求均值落在 265.072–272.784 kg，窗宽均值落在 43.766–45.538 min，服务均值落在 11.450–11.783 min；组间差异是固定经验池重采样差异，不是九城观测差异。

**INFERENCE—常识核对边界。** 数值与源工作簿给定的 08:00–11:00/13:00–19:00 业务时段内部相容，交付窗起点全部落在 11:07:47–17:52:06，窗宽全部落在 30.016–59.975 min。但本次覆盖的国家平台、竞赛、期刊和仓库检索没有找到“全国中国城配订单”的可引用基准分布，因而不能把上述范围提升为中国城配的一般统计规律。需求和服务都是体积的确定性函数，也不能作为两个相互独立的现实校验维度。

### 4. 原始观测、源案例派生与本项目变换

| 字段/语义 | 分类 | 说明与证据 |
|---|---|---|
| 订单号、呼入时间 | 发布数据字段 | Day 1–10 原始表头；是否由平台自动导出未披露 |
| 客户/商户平面 x、y | 发布数据字段 | 原始工作簿字段；城市与坐标系未披露；本项目没有把它们当九城 GIS 客户位置 |
| 取货/交付时间窗起止 | 发布数据字段 | 1,222 行保留源精度；当前正式基础使用交付窗 |
| 货物体积 m³ | 发布数据字段 | 只有 1.0/1.5/2.0/2.5/3.0 五档；没有实测 kg |
| 车辆号、更新时刻、车辆平面位置 | 发布数据字段 | 日文件车辆工作表；不是九城车队合同 |
| 7.2 m³ 车辆容量 | 论文案例参数 | Zhang PDF p.17 和 Data Description；不是每辆车现场测量 |
| 0.1 h/m³ 装卸率 | 论文案例参数 | Zhang PDF p.17 和 Data Description；不是逐站计时 |
| `demand_kg` | 本项目构造 | `round(volume_m3/7.2*1000)`；保持容量份额，不表达货物密度或实测重量；合同路径见上 |
| `service_time_min` | 本项目按论文参数派生 | `volume_m3*0.1*60`；结果 6/9/12/15/18 min；不得称实测停站时长 |
| 交付窗联合经验重采样 | 本项目构造 | 冻结种子、有放回、整行联合保留起点/宽度/映射需求/服务；不得拆分独立抽样 |
| 九城客户经纬度 | 本项目外部 GIS 构造 | 来自 China81 GIS/OSM 位置链，不是 Zhang 企业坐标；订单属性与九城位置是迁移组合 |
| “硬时间窗” | 本项目模型语义 | 源值是时间窗；Zhang 原模型允许罚金迟到，p.19 把硬时间窗列为未来工作 |

变换不会使数据失去 CC BY 4.0 下的可复用性，但会改变可作的经验主张。需求量和服务时长均为构造字段，GIS 位置与订单属性来自不同证据链；所以“真实中国订单”的不加限定说法会掩盖三个事实：单企业/单片区、九城迁移、kg/服务 proxy。`current_source_assessment.json` 给出机器可读的逐项边界。

## 第二部分：渠道覆盖与候选清单

### 1. 检索口径与命中数

“命中数”定义为：标题、摘要、数据页和许可经人工筛查后，进入本报告候选结构化清单的独立数据源数；不是搜索引擎返回网页总数。精确检索式、日期、URL 和判定见 `raw_runs.csv`。

| 渠道 | 核心检索式 | 命中数 | 说明 |
|---|---|---:|---|
| Solomon / Gehring-Homberger / Cordeau / CVRPLIB | `VRPTW Solomon benchmark demand time window service`; `Gehring Homberger`; `Cordeau MDVRPTW`; `Uchoa X CVRPLIB` | 4 | C06–C09 |
| VRP-REP / EVRP | `Schneider Goeke Montoya Froger EVRP instances download license` | 4 | C10–C13；VRP-REP HTTPS 失败，HTTP/DIMACS/Mendeley 回退可用 |
| 国家/省级平台、交通运输部 | `site:mot.gov.cn 物流 订单 客户 坐标 时间窗 数据集 城市配送`; `site:data.gov.cn`; 九城省市数据平台同义词 | 0 | 命中为行业汇总、政策、客货运量或监管制度，没有可公开下载的逐单位置+需求/时间窗 |
| 菜鸟/京东/顺丰/天池/华为竞赛 | `Tianchi logistics routing dataset time window`; `JD Logistics challenge routing`; `Huawei logistics challenge dataset`; `Cainiao LaDe` | 1 | C03 美团—INFORMS；JD 的 C02 来自论文配套数据而非竞赛；LaDe 沿用上一轮结论 |
| Kaggle 中国物流 | `site:kaggle.com/datasets China logistics delivery orders coordinates time window` | 0 | 返回印度/全球/合成运输表，未出现具名中国城市且满足三项中至少两项的源 |
| Transportation Science 近五年 | `site:pubsonline.informs.org transportation science dataset last mile routing data availability` | 2 | C03、C14；Froger 为 2022 论文但使用旧 Montoya 基准，计入 EVRP 渠道 |
| TR-B 近五年 | `site:sciencedirect.com/journal/transportation-research-part-b dataset vehicle routing data availability 2021..2026` | 0 | C12 Montoya 为 2017，按必查经典 EVRP 列入，不计近五年命中 |
| TR-E 近五年 | `site:sciencedirect.com/journal/transportation-research-part-e dataset vehicle routing open data 2021..2026` | 2 | C02、C15 |
| EJOR 近五年 | `site:sciencedirect.com/journal/european-journal-of-operational-research routing dataset open data 2021..2026` | 0 | C11 的论文为 2015；2022 是数据再发布 |
| Computers & OR / Omega 近五年 | 两刊域名 + `vehicle routing dataset open data` + `2021..2026` | 0 | 未发现满足字段与许可要求且可直接核查的数据页 |
| 《系统工程理论与实践》《管理科学学报》近五年 | 期刊域名/题名 + `车辆路径 数据 算例 附件` | 0 | 论文或表格算例不等于带独立许可的公开逐单数据 |
| Mendeley Data | `site:data.mendeley.com China logistics orders vehicle routing time windows`; EVRPTW DOI 复核 | 4 | C01、C10、C11、C15 |
| Zenodo | `site:zenodo.org/records EVRP time windows demand coordinates dataset` | 1 | C16 |
| Harvard Dataverse | API：`"vehicle routing" AND "time window"`；`"China logistics"` | 1 | C17 为 Harvard 搜索收录的 DataverseNL 数据；中国物流精确式 0 |
| IEEE DataPort | `site:ieee-dataport.org China logistics vehicle routing time window dataset` | 未得可核数 | 目录搜索被 robots 阻断，记入 `inaccessible.json` |
| ScienceDB | `site:scidb.cn vehicle routing time window 物流 订单 数据集` | 0 | 官方主页可访问；未找到符合字段门槛的数据页 |
| Figshare | `site:figshare.com logistics vehicle routing time window China dataset` + DOI 复核 | 2 | 当前 PLOS 源与 C02；当前源不重复计入新增候选数 |

上一轮 `docs/handoff/china_open_ev_vrp_instance_search_20260717.md` 已核过并不在此重复展开：Wang et al.（2025）重庆案例没有机器可读客户表；Cainiao LaDe 重庆交付表有位置和轨迹但无需求/承诺时间窗/车场/电池，且许可证口径冲突；北京充电站 Figshare 只有站点；七城 EV Zenodo 只有聚合驾驶/充电分布。上一轮总体结论 `HALT_NO_COMPLETE_OPEN_INSTANCE` 是“没有一份中国公开源同时给出多车场、EV/电池、站点、客户需求和时间窗”，本次新增源也没有同时补齐这些字段。

### 2. 中国或中国业务候选

#### C01 SN Data（武汉零碳区）

- 链接/DOI/许可：[Mendeley Data](https://data.mendeley.com/datasets/gsnndmbyzc/1)，DOI `10.17632/gsnndmbyzc.1`，CC BY 4.0，v1，2026-07-12。
- 出处：Mendeley Data（Elsevier 数据仓库）；数据页只列贡献者 Jiangcen Ke，未列相关已发表论文或机构，不能把仓库品牌等同于论文同行评审。
- 中国性：武汉市零碳区交通限制；客户和车辆去标识；数据页称订单为“de-identified and processed”。
- 字段：4,107 单，174 个客户；订单有 ID、kg、m³、开始/结束时间、客户 ID、服务分钟、经纬度、区域和到边界距离；500 辆车有车辆 ID、油/电类型、kg/m³容量、单位成本和启动成本；另有距离矩阵、禁行规则和动态事件伪代码。
- 样本/跨度：工作簿起始时间覆盖 2025-01-01 至 2025-01-02，窗口全部为 4 h；数据页未说明这两日是否为完整业务日。动态响应是预定义情景的软件仿真，不是实时运营采集。
- 适配事实：坐标、需求、时间窗、服务和混合车队齐全；没有多车场归属、充电站/电池/充电曲线、明确多趟或九城覆盖。若迁入，需要重建订单合同、车队合同、车场映射、能源/碳时序与可行性检查；会影响 `china_order_attribute_*`、China81 `orders.csv`、实例元数据/哈希以及依赖这些输入的既有实验产物。四小时时窗与当前约 30–60 min 窗不是同一业务口径。

#### C02 JD.com 移动换电配送案例

- 链接/DOI/许可：[Figshare 数据页](https://figshare.com/articles/dataset/Delivery_routing_for_electric_vehicles_with_en-route_mobile_battery_swapping/26870551)，数据 DOI `10.6084/m9.figshare.26870551.v1`，CC BY 4.0；论文 [Transportation Research Part E](https://doi.org/10.1016/j.tre.2024.103838)。期刊页面在本次访问显示 2024 Impact Factor 8.8。
- 中国性：数据页明确为 JD.com 提供的四个现实案例；`input_node.xlsx` 有 1,201 个节点，坐标落在北京一带，但数据页未明写城市，因此“北京”只能标作坐标推断，不能当来源声明。
- 字段：源节点有经纬度、包裹总重量 t、总体积、最早/最晚收货时刻；四个抽样案例为 150/150/200/200 客户，文本字段为 NodeID、x、y、demand、ReadyTime、DueDate、ServiceTime；另含 EV 与移动换电车容量、能耗、速度和换电参数。
- 时间跨度：数据页未披露采集日期或持续天数。
- 适配事实：有位置、需求和窗口字段，但四个 txt 中出现 `ReadyTime > DueDate`，例如 `150-1` 第 1 客户为 120/30；在解释规则未补齐前，`DueDate` 不能直接当绝对硬窗上界。单车场、纯电配送+移动换电车，不是当前油电混合、多车场、多趟模型。迁入需先解决时间字段语义，再重建订单/车场/车队/补能接口与九城碳时序；影响与 C01 同类的输入和下游产物。

#### C03 Meituan–INFORMS TSL 运营级外卖数据

- 链接/DOI/许可：[INFORMS TSL 挑战页](https://connect.informs.org/tsl/tslresources/datachallenge)、[GitHub 数据仓库](https://github.com/meituan/Meituan-INFORMS-TSL-Research-Challenge)、[SSRN 数据说明稿](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5696423)，说明稿 DOI `10.2139/ssrn.5696423`；GitHub 数据集本身未给 DOI。另有一篇使用该数据的 Transportation Science 论文 DOI `10.1287/trsc.2025.0129`，不是数据说明稿。仓库 `License.txt` 为 CC BY-NC 4.0，并附“未经许可不得向第三方再分发”和发表致谢要求；应同时遵守这些明示条件。
- 出处：美团与 INFORMS Transportation Science and Logistics Society；数据说明稿是 SSRN 预印本，挑战由 INFORMS TSL Society 与 Transportation Science 联合举办，另有使用该数据的 Transportation Science 论文。Transportation Science 官方列 2024 IF 4.8，OR & Management Science 21/106（Q1）、Transportation Science & Logistics 22/77（Q2）。
- 中国性：一个匿名中国中等城市，坐标整体平移；2022-10-17 至 2022-10-24 八天。
- 字段/样本：568,546 个订单、654,343 个 waybill、4,955 名骑手、4,962 个商户；订单表含商户与客户位置、创建/推送/指派/接单/取餐/送达时间、承诺送达时间、预计备餐完成时间、预订单/周末标志；另有骑手波次与派单候选表。没有货物重量/体积或车辆载重，服务时长需由事件时间定义而不能直接等同当前停站服务参数。
- 适配事实：客户位置与承诺时刻齐全，需求量缺失；是即时取送和动态指派，不是仓库向客户的静态 LTL 配送。若只作订单到达/承诺时刻对照，需要定义外卖到货运订单的迁移边界；若替换主算例，还需构造需求、车场、车队、电池、站点与多趟规则，并重建全部 China81 输入及下游产物。

#### C04 上海大规模 VRPTW/MDVRPTW

- 链接/DOI/许可：[GitHub 数据目录](https://github.com/spatialsmart/VRPTW/tree/master/Shanghai/Problem)；论文 [ISPRS International Journal of Geo-Information](https://doi.org/10.3390/ijgi4042019)，DOI `10.3390/ijgi4042019`。论文为 CC BY 4.0；GitHub 仓库没有独立 LICENSE，故数据文件的独立许可未声明，不能自动把文章许可扩大为仓库许可。
- 中国性：上海商业 POI 的现实空间位置；客户属性是仿真生成，不是企业订单；不匿名到个人，但投影坐标不含客户身份。
- 字段/样本：10 个实例；5 个单车场 VRPTW 与 5 个多车场 MDVRPTW，客户数 2,000/4,000/6,000/8,000/10,000，多车场数 2–6；字段为 x/y、服务时长、需求、时间窗、路线时长和容量。商业 POI 随机抽取，窗宽随机 30–60 min，服务随机 1–4 min，需求随机 1–100。
- 适配事实：坐标、需求、硬时间窗、服务、多车场齐全；没有混合车队、电池/站点或多趟。窗宽 30–60 min 与当前窗口范围接近，但它是作者随机设定，不能用作中国企业时间窗分布的独立支持。迁入需完成许可澄清、尺度/坐标/单位映射、车队与补能扩展，并重建九城输入和下游产物。

#### C05 大连水产品 25 单案例

- 链接/DOI/许可：[《大连海洋大学学报》文章](https://xuebao.dlou.edu.cn/article/2025/2095-1388/202502014.html)，DOI `10.16535/j.cnki.dlhyxb.2024-193`。网页未声明表 2 数据的独立开放许可，使用需另行确认权利。
- 出处：大连海洋大学主办期刊；本次核查页未显示 JCR 分区或 Impact Factor。
- 中国性：大连市某水产品配送企业，25 个大连及周边城市客户；企业匿名，调研日期未披露。
- 字段/样本：表 2 为图片/网页 OCR，含平面 x/y、kg、箱体长宽高、需求窗下限、最佳窗下/上限、需求窗上限、服务时间；两辆同型 2,300 kg 车辆，单配送中心。
- 适配事实：位置、kg、窗和服务齐全，但非机器可读独立数据包，时间窗模型允许满意度随迟到变化，且无许可、EV/站点、多车场、多趟。若取得作者授权并人工复核表格，需要双人转录与哈希审计，再重建订单/车队/空间与能源链；25 单只覆盖一个小案例。

### 3. 标准与国际候选

#### C06 Solomon VRPTW

- 链接/许可：[SINTEF VRPTW](https://www.sintef.no/projectweb/top/vrptw/)；原论文 `10.1287/opre.35.2.254`。SINTEF 公开下载，但页面未声明数据许可证。
- 出处：SINTEF 托管的社区基准；原论文发表于 Operations Research。
- 区域/样本：非中国、完全合成；56 个实例，每个 100 客户，R/C/RC 与短/长时域组合；无日历跨度。
- 字段：平面坐标、需求、ready/due、服务时间、单车场、同质车辆容量；无 EV/站点。
- 适配事实：可作标准 VRPTW 对照；不直接含多车场、混合车队、多趟。迁移为当前模型需加入车场、车型、能源/碳和多趟语义；若替换 China81，会影响所有输入与结果，若只作外部算法对照则可隔离新建基准链。

#### C07 Gehring & Homberger VRPTW

- 链接/许可：[SINTEF Gehring–Homberger 页面](https://www.sintef.no/projectweb/top/vrptw/1000-customers/)；公开下载，数据许可未声明。
- 出处：SINTEF；原作者 Gehring & Homberger。
- 区域/样本：非中国、合成；200/400/600/800/1000 客户，每个规模 60 个实例，合计 300；无日历跨度。
- 字段：与 Solomon 同构，含坐标、需求、硬时间窗、服务、单车场同质容量；无 EV/站点。
- 适配事实与迁移：同 C06，但规模可覆盖当前 200 客户以上的算法压力测试；不能提供中国真实性或混合车队/多趟事实。

#### C08 Cordeau MDVRPTW

- 链接/许可：[NEO VRP 实例库](https://neo.lcc.uma.es/vrp/vrp-instances/)、[20 个实例页](https://www.bernabe.dorronsoro.es/vrp/Problem_Instances/MDVRPTWInstances.html)。公开下载，数据许可未声明。
- 出处：Cordeau 等经典 MDVRPTW；NEO Research Group 汇编。
- 区域/样本：非中国、合成；20 个 `pr01–pr20`，48–288 客户、4 或 6 车场，紧/宽时间窗；无日历跨度。
- 字段：客户/车场平面坐标、需求、时间窗、服务、容量、路线时长、各车场车辆数；无 EV/站点。
- 适配事实：多车场与硬窗直接存在；混合车队、电池、充电和多趟缺失。可只作为结构对照，也可经显式扩展形成新构造链；后一方式会重建车队/能源字段和下游产物，但不能称中国订单。

#### C09 Uchoa X / CVRPLIB

- 链接/许可：[DIMACS CVRP 说明](https://dimacs.rutgers.edu/index.php/programs/challenge/vrp/cvrp/)、[CVRPLIB](https://galgos.inf.puc-rio.br/cvrplib/)。公开下载，数据页未声明统一数据许可证。论文 DOI `10.1016/j.ejor.2016.08.012`，发表于 EJOR。
- 出处：PUC-Rio CVRPLIB 与 DIMACS Challenge。
- 区域/样本：非中国、合成；X 集 100 个实例，100–1,000 客户；无日历跨度。
- 字段：坐标、需求、容量、单车场；没有时间窗、服务、车辆异质性或补能。
- 适配事实：只能直接检验 CVRP 路由/容量层。若迁入完整模型，必须构造时间窗、服务、车场、车型与能源；这些构造不能作为现实中国订单证据。

#### C10 Schneider E-VRPTW

- 链接/DOI/许可：[Mendeley Data](https://data.mendeley.com/datasets/h3mrm5dhxw/1)，DOI `10.17632/h3mrm5dhxw.1`，CC BY-NC 3.0；论文 DOI `10.1287/trsc.2013.0490`，Transportation Science 48(4)。期刊官方当前指标见 C03。
- 区域/样本：非中国、基于 Solomon 的合成实例；36 个 5/10/15 客户小实例与 56 个 100 客户实例、后者含 21 个站；无日历跨度。
- 字段：节点类型、坐标、需求、ready/due、服务、充电站、同质 EV 容量/电池/能耗/充电率。
- 适配事实：硬窗与补能齐全；单车场、纯 EV、单趟，不含混合车队和时变电网碳。迁入需加入 CV、车场、跨趟与碳时序；可隔离作 EVRP 结构对照。

#### C11 Goeke–Schneider EVRPTW-MF

- 链接/DOI/许可：[Mendeley Data](https://data.mendeley.com/datasets/bd7rm5fw6k/1)，DOI `10.17632/bd7rm5fw6k.1`，CC BY 4.0；论文 DOI `10.1016/j.ejor.2015.01.049`，EJOR 245(1)。
- 区域/样本：非中国、合成；本地只读核对 `models/data_bundle/raw_instances/goeke_uk/` 为 180 个文件，10/15/20/25/50/75/100/150/200 客户各 20 个。
- 字段：节点类型、坐标、需求、ready/due、服务、站点；EV 与常规车的容量、成本、能耗/油耗参数。
- 适配事实：混合车队、需求、硬窗和补能直接存在；单车场、单趟，不含中国空间或时变碳。迁入主要需扩展多车场、多趟与碳时序；若仅作结构对照，不应改写 China81 原数据链。

#### C12 Montoya E-VRP-NL

- 链接/许可：[DIMACS EVRP 页面与下载](https://dimacs.rutgers.edu/index.php/programs/challenge/vrp/evrp/)，VRP-REP ID 2016-0020；VRP-REP 页面未声明数据许可。论文 DOI `10.1016/j.trb.2017.02.004`，Transportation Research Part B；Elsevier 页面本次显示 IF 6.3。
- 区域/样本：非中国、合成；120 个实例，10/20/40/80/160/320 客户各 20 个；无日历跨度。
- 字段：坐标、单位需求、服务、充电站、路线时限、Peugeot iOn 16 kWh 与 0.125 kWh/km、非线性充电曲线；客户没有时间窗。
- 适配事实：非线性补能可直接对照，但硬窗、混合车队、多车场、多趟缺失。迁入完整模型需补齐这些结构；任何新增时间窗都是新构造。

#### C13 Froger E-VRP-NL-C

- 链接/许可：[DIMACS EVRP 页面](https://dimacs.rutgers.edu/index.php/programs/challenge/vrp/evrp/)，论文 DOI `10.1287/trsc.2021.1111`；数据许可未在 DIMACS/VRP-REP 页面声明。论文发表于 Transportation Science 56(2)，期刊当前指标见 C03。
- 区域/样本：非中国、合成；由 Montoya 120 个实例分别设置每站 1 或 2 个充电器，形成 240 个容量化站点实例。
- 字段：继承坐标、单位需求、服务、站点、EV/非线性曲线与路线时限，并增加充电器数量；无客户时间窗。
- 适配事实：可对照共享站容量与非线性补能；不直接满足硬窗、混合车队、多车场、多趟。迁入需构造缺失结构，并重建充电资源/碳时序接口。

#### C14 Amazon Last Mile Routing Challenge

- 链接/DOI/许可：[AWS Registry](https://registry.opendata.aws/amazon-last-mile-challenges/)，CC BY-NC 4.0；数据论文 DOI `10.1287/trsc.2022.1173`，Transportation Science；Amazon 与 MIT CTL 联合。
- 区域/匿名：美国 Seattle、Los Angeles、Austin、Chicago、Boston；2018 年；坐标扰动，路线/包裹 ID 重生成。
- 字段/样本：6,112 条训练路线 + 3,072 条评估路线，共 9,184；路线含站点/车场、日期、出发时间、车辆体积容量、历史顺序、成本矩阵；包裹含尺寸、重量、客户时间窗和计划服务时间。
- 适配事实：现实位置、需求特征、窗和服务齐全；每条历史路线以一个站点出发，多站点跨样本存在，但不是当前多车场联合分配；无 EV/电池、多趟。迁入需把包裹聚合到客户、定义硬窗冲突处理、加入混合车队/能源/碳和多趟；地域不支持中国实证主张。

#### C15 MFVRP-LEZ

- 链接/DOI/许可：[Mendeley Data v2](https://data.mendeley.com/datasets/np452gmj7f/2)，DOI `10.17632/np452gmj7f.2`，CC BY 4.0；论文 DOI `10.1016/j.tre.2025.104230`，Transportation Research Part E 201，期刊页面本次显示 2024 IF 8.8。
- 区域/样本：基准部分由 Schneider 派生；36 个 5/10/15 客户小实例和 56 个 100 客户大实例的 type-1 子集/LEZ 变体；另有米兰 Area C 案例，30 个随机客户、真实道路距离。不是中国。
- 字段：坐标、需求、硬时间窗、服务、充电站、EV/ICEV 混合车队、低排放区几何、成本与充电参数。
- 适配事实：作者明确只保留短时域/窄窗 type-1，并说明省略 type-2 是因为宽窗对充电决策影响较小；这说明该基准是机制特定构造，不是中性现实窗口分布。单车场、单趟；迁入需加多车场、多趟、时变碳和中国空间，且不得因窄窗更易显现机制而事后选择。

#### C16 EVRP-TW-D

- 链接/DOI/许可：[Zenodo v1.1](https://zenodo.org/records/18529191)，DOI `10.5281/zenodo.18529191`，CC BY 4.0；作者机构 University of California, Riverside，仓库由 CERN/OpenAIRE 基础设施提供。
- 区域/样本：20 个北美服务区，真实地理、半合成；4 个规模 5/15/50/100，每区每规模 20 个运营日实例，共 1,600；v1.1 于 2026-02-09 发布。
- 字段：道路节点/边、客户候选、公共充电站候选、车场候选；实例含需求、服务、时间窗、客户/站点激活和 EV 参数。数据页明确：地理来自 Census/ACS/OSM/NREL 等公开源，日需求、服务、窗和激活由生成器产生。
- 适配事实：EV、位置、需求、硬窗、服务和站点齐全；不是中国，日属性是生成值，且默认不提供当前油电混合、多车场联合、多趟语义。迁入需选择车场/车型扩展和时变碳映射；527.7 MB 数据包也会增加重建与审计成本。

#### C17 Consistent Collaborative Vehicle Utilization 实例

- 链接/DOI/许可：[DataverseNL](https://doi.org/10.34894/3SK3JG)，DOI `10.34894/3SK3JG`，CC BY 4.0，v1.0，2025-06-24；论文 DOI `10.1002/net.70041`，Wiley Networks；作者机构 University of Groningen。该项由 Harvard Dataverse API 精确式命中，但实际发布仓库是 DataverseNL。
- 区域/样本：非中国、合成/由既有基准扩展；40 个 Excel（pr/sr 各 10 个、20/50 客户），另有说明文件；多承运人、多周期。
- 字段：客户 x/y、服务时间、需求、需求周期、所属公司、利润；车场 x/y、车辆数。离散可选时间段在模型层设置，文件没有每客户 hard ready/due；车辆可跨承运人借用。
- 适配事实：坐标、需求、多车场/多承运人与多周期齐全，但没有 EV/站点、当前意义的逐单硬窗或多趟。迁入需构造时间窗与能源/碳层；它适合检验协同/车场结构，不提供中国订单真实性。

### 4. 迁移影响的共同边界

上述“迁移”均只是工作量事实，不是实施决定。若任何源替换当前订单属性主链，至少需要新建而不是静默覆盖以下环节：来源合同与批准登记、原始数据清单/许可记录、字段映射和单位合同、冻结抽样或实例选取规则、九城 GIS/车场连接、车辆/电池/站点与时变碳输入、可行性回放、实例 metadata/decision/hashes，以及所有依赖旧 China81 输入的实验与论文表图。若仅增加外部对照，可以建立隔离基准链而不改写当前源，但仍需预先冻结比较目的和转换规则。

时间窗“更窄/更宽”、电池“更小/更大”或某源可能让机制数值更明显，均不构成数据源取舍依据。C15 的作者确实按机制理由保留 type-1 窄窗，C02 数据说明把 type-1 定义为更短时域/更紧窗口；这些只是来源设计事实，同时意味着它们不代表无条件的现实分布。

## 第三部分：访问不到的端点

完整机器记录见 `inaccessible.json`。本次未因单个端点失败停止渠道检索：

| 端点 | 失败 | 回退与边界 |
|---|---|---|
| `https://www.vrp-rep.org/` | LibreSSL `SSL_ERROR_SYSCALL`，HTTP code 000 | `http://www.vrp-rep.org/` 返回 200；Montoya/Froger 内容另由 DIMACS 和论文核对，故不是整源不可访问 |
| IEEE DataPort 目录检索 | web 检索被 `robots.txt` 非重试阻断 | 首页可返回 200，但无法核查目录结果/许可/字段；因此该渠道命中数不写 0，而写“未得可核数” |
| `https://search.mot.gov.cn/...` | DNS：`Could not resolve host: search.mot.gov.cn` | 改用 `mot.gov.cn`/`xxgk.mot.gov.cn` 域名限定检索；只命中汇总统计和政策 |
| `https://www.scidb.cn/en/search?keyword=...` | HTTP 404 | ScienceDB 官方主页可访问；改用 `site:scidb.cn` 检索，未得到合格数据页 |
| MDPI 文章 HTML | HTTP 429 | 官方 PDF、DOI 页和作者 GitHub 数据目录可访问；C04 内容有回退证据 |

## 复核声明

本报告没有运行 solver、没有生成或改写任何算例、没有读取实验结果来选择数据源、没有候选排序或评分。结构化事实见 `current_source_assessment.json` 与 `candidates.json`；检索留痕见 `raw_runs.csv`；本任务状态见 `decision.json` 和 `metadata.json`。
