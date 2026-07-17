# 中国背景公开 EV 配送算例检索判决

日期：2026-07-17  
工作目录：`/Volumes/移动硬盘（512G）/ReSETP`  
分支：`codex/reporting-pipeline`  
任务边界：只检索、打开页面/论文、尝试获取公开数据元信息；没有运行优化、没有修改算法代码、没有使用候选数据启动实验。

## 总判决

**FOUND_PARTIAL**

本轮没有找到一个同时满足“真实中国背景、至少两个车场、EV 电池/能耗/充电站、客户时间窗、50--200 客户级、原始文件可直接下载、学术使用和再分发许可清楚”的公开算例包。

最接近的候选是 Wang 等人在重庆案例上的多车场电动车时间窗研究：论文正文同时明确了 4 个车场、151 个客户、13 个充电站和时间窗，并且另有约 48--192 客户的派生实例规模。它满足四要素的“论文案例层”要求，但 Data Availability 只说数据包含在文章内，没有逐客户/逐车场/逐充电站的机器可读文件、坐标系说明或独立数据许可。因此它不能直接作为可再分发的现成 benchmark。

首选建议：把重庆案例作为 C31 自建数据的业务校准和参数来源，而不是把论文表格当作已下载算例。若作者能补充原始表格，估计 1--3 个工作日可完成格式化、字段审计和 3×3 规模缩放；若只能依据论文正文和图表重建，估计 3--5 个工作日，且坐标、车辆参数和动态需求重建存在不可消除的不确定性。这是工作量估计，不是已验证事实。

第二顺位是 2026 年 Computers & Operations Research 论文披露的 JD.com 北京数据：论文实际给出 GitHub 数据入口，且正文描述了 1 个 depot、1,100--1,500 客户和 100 个充电站。它有中国业务、EV 和时间窗，但不是多车场；仓库文件、许可、字段和坐标系在本轮无法打开，所以只能作为“待复核数据线索”。

因此本轮不授权把任何候选直接接入 `C31` 或后续优化；若要保持审计闭合，当前仍应按“公开数据不足，继续自建”处理，除非后续取得重庆原始数据或成功核验 JD 仓库许可与文件。

## 判定口径与证据边界

四个硬要素按以下规则逐项判定：

| 标记 | 含义 |
|---|---|
| `✓` | 在已打开的论文正文、数据页面或文件说明中明确看到；不是根据标题推测。 |
| `✗` | 已打开材料明确缺少该要素。 |
| `?` | 页面、文件或正文没有足够证据；不把它算作满足。 |
| `↗` | 现有公开材料不满足，但可以自然改造；改造后仍需重新做可行性和许可证审计。 |

“中国背景”要求真实城市/业务描述或明确中国场景；“中国作者”本身不算。多车场要求公开材料实际出现至少两个 depot，单 depot 只能记 `↗`。许可证只针对实际列出的数据文件判断，论文开放获取不自动等于原始数据可再分发。规模以公开材料中的客户数为准，只有“可以从大实例抽样”时记 `↗`，不把未经验证的抽样当成现成 50--200 客户数据。

## 候选总表

| 候选 | 已打开的证据/配套文档 | 中国背景 | 多车场 | EV 要素 | 客户时间窗 | 50--200 客户级 | 许可、下载与文件结构 | 判决 |
|---|---|---:|---:|---:|---:|---:|---|---|
| 重庆 MDEVRPTW-DD（Wang 等，2025） | [Sustainability 17(6):2700](https://www.mdpi.com/2071-1050/17/6/2700) | ✓ | ✓ | ✓ | ✓ | ✓ | 论文页面可读；Data Availability 写数据包含在文章内，没有单独原始包或数据许可；无法直接下载机器可读文件 | 四要素最完整，但 `PARTIAL` |
| JD.com 北京 E-VRP-HC（Wang 等，COR 2026） | [ScienceDirect 论文页](https://www.sciencedirect.com/science/article/abs/pii/S0305054825004034)、[可读 PDF](https://chairelogistique.hec.ca/wp-content/uploads/2025/05/Electric-Vehicle-Routing-with-Heterogeneous-Charging-Stations-1.pdf) | ✓ | ✗（单 depot） | ✓ | ✓ | ↗（公开规模 1,100--1,500，需有依据地截取） | 论文给出 [GitHub 入口](https://github.com/wwq-uibe/E-VRP-HC)，但仓库、许可、压缩包和字段本轮未验证；不能声称已下载 | 中国数据线索，`PARTIAL` |
| JD GOC 城市物流挑战赛（2018） | [JD GOC 介绍](https://medium.com/jd-technology-blog/highlights-from-the-global-optimization-challenge-17f4ad357337)、[中文报道](https://m.ikanchai.com/pcarticle/213677) | ✓ | ? | ✓ | ✓ | ↗（介绍称 1500+ 节点） | 官方页面说明真实 JD 订单、异构车队、容量、时间窗和充电站；没有公开文件、字段或许可；[Gitee 镜像线索](https://gitee.com/liuyahui/GOC-EVRPTW) 未能打开仓库树，不能核验 | 公开数据不可核验，`PARTIAL` |
| Mendeley `MDVRPDRL_Data` | [数据页](https://data.mendeley.com/datasets/967gj8rn44/1) | ✗（二维均匀合成坐标） | ✓ | ✗ | ✓ | ✓（20/50/100） | 页面列 CC BY 4.0 并有 Download All；本轮未能把文件落盘，字段仍以页面描述为准；可作为多车场/TW 基底，需另加中国地理和 EV 层 | 可合法改造的通用基底，`PARTIAL` |
| Zenodo EVRPTW 异质充电站数据（2026） | [数据论文](https://www.mdpi.com/2306-5729/11/4/83)、[Zenodo DOI](https://doi.org/10.5281/zenodo.19443014) | ✗（合成） | ✗（单 depot） | ✓ | ✓ | ↗（公开主实例 1000，需截取） | 论文描述 CC BY 4.0、TXT/CSV/JSON 结构和充电站属性；不是中国、多车场；本轮未能把 Zenodo 压缩包落盘 | 结构清楚但改造量大，`PARTIAL` |
| Mendeley ESOGU-CEVRPTW | [数据页](https://data.mendeley.com/datasets/7vjzvxh72d/1)、[配套论文](https://www.mdpi.com/2076-3417/15/3/1068) | ✗（土耳其校园） | ✗（1 depot） | ✓ | ✓ | ✓（最大 60） | 页面列 CC BY-NC-ND 4.0；非商业、禁止衍生/改编，不适合作为 C31 再分发基底；118 客户来源、10 充电站、45 个 TXT 实例在论文中明确 | 要素较近但许可和地域不合，`PARTIAL` |
| Mendeley ESOGU-EVRP-PD-TW | [数据页线索](https://data.mendeley.com/datasets/s88zf59nm9/1) | ✗（土耳其校园） | ✗（1 depot） | ✓ | ✓ | ↗（页面检索摘要列到 100） | 页面正文在本轮未完整打开，CC BY 4.0、文件结构和下载状态均标为未验证 | 未验证，`PARTIAL` |
| Zenodo 2E-EVRP v2 | [Zenodo 记录](https://zenodo.org/records/14844216)、[Data in Brief 论文](https://www.sciencedirect.com/science/article/pii/S2352340925002021) | ✗（随机/聚类基准） | ↗（有 satellite，但不是本文单层多 depot 语义） | ✓ | ✓ | ✓（50/100） | 页面实际列出 `2E-EVRP-Instances-v2.zip`、4.1 MB、CC BY 4.0 和页面 MD5；源包本轮未落盘；可作格式参照，不能作中国实例 | 开放许可的非中国基底，`PARTIAL` |
| Figshare FEVRPTW | [Figshare 数据页](https://figshare.com/articles/dataset/Fuzzy_optimization_model_for_electric_vehicle_routing_problem_with_time_windows_and_recharging_stations/10288326)、[配套 ESWA 论文](https://www.sciencedirect.com/science/article/pii/S0957417419308401) | ?（未看到中国场景） | ? | ✓ | ✓ | ? | 页面列 CC BY 4.0、7.5 MB 并给出下载入口；直接 ndownloader 请求本轮 cache miss，未检查文件结构；没有验证中国/多车场/规模 | 仅能作 EVRPTW 参照，`PARTIAL` |
| 深圳 `ST-EVCDP` / UrbanEV | [GitHub 仓库](https://github.com/IntelligentSystemsLab/ST-EVCDP) | ✓ | ✗（无配送 depot） | ✓（充电桩、位置、容量和时序） | ✗（无配送客户时间窗） | ✗ | 公开仓库包含深圳充电基础设施数据线索；本轮没有把客户/订单/时间窗数据识别出来，仓库数据许可未单独核验 | 可补充充电站层，不是 EVRP，`PARTIAL` |
| CVRPLIB 与 NEO 周边库 | [CVRPLIB wrapper](https://github.com/Fedoration/CVRPLIB)、[CVRPLIB XML100](https://galgos.inf.puc-rio.br/cvrplib/en/xml100)、[NEO VRP instances](https://neo.lcc.uma.es/vrp/vrp-instances/) | ✗ | ↗（NEO 有多 depot 类别，但 EV 层没有） | ✗ | ✓（VRPTW） | ✓（100/200 等） | wrapper 为 MIT；底层实例许可未统一验证；提供 depot/customer/demand/service/TW 等传统字段，没有 EV 电池/充电站和中国坐标 | 只能作传统 VRPTW/MDEVRPTW 几何底板，`PARTIAL` |

上表中“`PARTIAL`”不是说候选没有研究价值，而是说在四要素和“可直接复用”合约下不能判 `FOUND_USABLE`。

## 重点候选证据

### 1. 重庆多车场案例：四要素满足，但缺机器可复用数据层

我打开了论文正文页面，而不是只看标题。论文明确建模多车场、电动车、充电站、客户时间窗和动态客户需求；实验部分把 Chongqing 作为实际案例，描述了 4 个车场、151 个客户（101 静态、50 动态）和 13 个充电站。论文还说明有从 NEO MDVRPTW 派生并加入充电站和动态需求的 30 个实例；公开表格中的客户规模组合包含约 48、96、144、192 等级，覆盖了 C31 所需的 50--200 客户量级附近。

但论文没有提供可下载的客户表、车场表、充电站表、车辆表或坐标文件，正文也没有足够的逐行 schema。公开页面的 Data Availability 是“数据包含在文章内”的口径，不能从中推导出一个允许再分发的原始数据包。论文中出现的业务背景可以用于参数校准，不能代替机器可读数据和许可证。

若要以它为 C31 的自建参照，最低补齐项是：明确三个中国区域的 depot/customer/charging-station 坐标或坐标生成规则，公开客户需求与时间窗表，固定电池/能耗/充电参数，说明 50/100/200 三个规模的抽样或生成关系，并给每个生成实例记录来源、版本和哈希。若拿不到原始数据，最终产物应称为“受重庆论文约束的自建算例”，不能称为“重庆公开原始算例”。

### 2. JD.com 北京数据：公开入口已在论文中出现，但多车场和仓库访问仍是硬门

我打开了 COR 论文页面和可读 PDF。论文把真实 JD.com 数据描述为北京实例，并给出 1 个 depot、1500 个客户、100 个充电站的图示以及 `C1500_S100` 到 `C1100_S100` 的实例命名。论文还明确指出 JD 原始数据没有充电技术、等待函数和充电价格，作者用文献/其他来源补充了这些属性；这意味着即便仓库可下载，也必须区分 JD 原始字段和论文补充字段。

论文正文给出 `https://github.com/wwq-uibe/E-VRP-HC` 作为数据/代码入口，但本轮没有打开仓库树和原始文件，不能验证 README、LICENSE、客户 CSV/TXT 列名、坐标系、车辆容量、电池字段或再分发条件。模型还是单 depot；增加第二个 depot 不是改一行配置，而是要补 depot 坐标、车辆归属/起终点、客户分区和可行性重算。由于公开规模远大于 C31，50--200 客户子集也必须有明确抽样规则，不能任意截取。

### 3. JD GOC：业务描述很强，数据可获得性很弱

JD 的公开介绍明确写到城市货运车辆路径与调度、容量、随机需求、取送、客户时间窗、异构车队和电动充电站，且规模是 1500+ 节点；中文报道还把它描述为基于 JD 真实用户订单的城市物流问题。这足以证明中国业务和 EV/TW 研究背景，但没有证明公开数据文件对外再分发。多车场在已打开材料中没有明确出现，不能按满足处理。搜索到的 Gitee `GOC-EVRPTW` 只是仓库线索，本轮没有成功读取实际树、文件和许可证。

## 按检索面覆盖情况

### 中国企业和竞赛公开数据

| 检索面 | 已核查内容 | 结果 |
|---|---|---|
| 京东物流 GOC | JD 官方技术文章、中文报道和 GOC-EVRPTW 镜像线索 | 业务描述包含中国城市、EV 充电、时间窗和大规模节点；没有核验到可下载原始包、许可或多 depot。 |
| 阿里天池物流/车辆调度 | [天池数据集专题页](https://tianchi.aliyun.com/specials/promotion/Dataset)、[天池数据集入口](https://tianchi.aliyun.com/dataset/)、物流/交通竞赛入口 | 页面能证明有物流调度、轨迹/交通等开放数据，但本轮没有打开一个同时包含 EV、客户 TW 和多 depot 的实际数据文件。 |
| 华为/顺丰 | [华为物流解决方案](https://www.huaweicloud.com/intl/zh-cn/solution/logistics/index.html)、[顺丰 2024 年报 PDF](https://www-static.sf-express.com/uploads/2024_43079617d0.pdf) | 能看到路线规划、时间窗或电动化业务背景；没有发现可下载 EVRP/MDEVRP 客户算例及其许可。 |

### 数据仓库和代码仓库

| 检索面 | 结果 |
|---|---|
| Mendeley Data | 找到 `MDVRPDRL_Data`、ESOGU-CEVRPTW、ESOGU-EVRP-PD-TW。前者是 CC BY 的多 depot/TW 合成数据但无中国/EV；后两者有 EV/TW 但土耳其、单 depot，且前者 CC BY-NC-ND。 |
| figshare | 找到 FEVRPTW 数据页，页面列 CC BY 4.0 和下载入口；没有验证中国、多 depot 和 50--200 规模，直接下载本轮 cache miss。 |
| Zenodo | 找到 EVRPTW 异质充电站数据、2E-EVRP v2、EVRP-TW-D、ETTRPTW 和深圳 UrbanEV 等线索。2E-EVRP v2 的 CC BY/文件/50、100 客户元数据实际可读，但地理是合成且 satellite 不等于 C31 单层多车场；深圳 UrbanEV 是充电基础设施，不是配送算例。 |
| IEEE DataPort | 本轮检索被站点 `robots.txt` 阻断，没有形成可引用的具体候选；不把搜索摘要当作已验证数据。 |
| GitHub 学术仓库 | 实际验证到 `IntelligentSystemsLab/ST-EVCDP` 的深圳充电数据说明；`wwq-uibe/E-VRP-HC` 和 GOC 镜像只验证到论文/搜索入口，未验证原始文件或许可证。 |
| CVRPLIB 及周边 | CVRPLIB/NEO 能提供传统 VRPTW、MDVRPTW 和 100/200 客户级基底，但没有中国背景和 EV 电池/充电字段。 |

### 近三年中文期刊与英文期刊

中文期刊中，重庆两篇论文最接近但方向不同：2025 年多车场 EVRP-TW 论文满足四要素但没有原始数据包；2022 年重庆动态需求多车场论文有 5 个车场、200 个客户和时间窗，却没有 EV/电池/充电站（[Sustainability 14(11):6709](https://www.mdpi.com/2071-1050/14/11/6709)）。另外实际打开的中文期刊页面包括：

- [部分充电策略下的多车型电动汽车车辆路径优化问题研究](https://jtgc.cbpt.cnki.net/portal/journal/portal/client/paper/JTGC_1aec799c-a4a5-4df9-bf99-55c8b6c6e124)：EV、电池/充电和时间窗明确，实验有 50 客户，但没有多 depot、真实中国坐标或公开数据附件。
- [时变路网下电动冷藏车配送路径优化研究](https://iej.gdut.edu.cn/article/doi/10.3969/j.issn.1007-7375.2022.04.008)：EV、充电站和时间窗明确，页面显示资源附件为 0；未验证多 depot、真实中国客户坐标和数据许可。
- [基于混合补能方式的开放式时变电动车配送路径规划](https://sysmath.cjoe.ac.cn/jweb_xtkxysx/CN/10.12341/jssms22859)：模型描述客户坐标/需求/时间窗、充电/换电和电池，但没有公开机器可读实例，也没有多 depot 证据。
- [电动汽车物流配送系统的换电站选址与路径优化问题研究](https://www.zgglkx.com/CN/10.16381/j.cnki.issn1003-207x.2015.09.011)：中国物流背景和 EV/电池/换电站明确，但没有验证客户时间窗、多 depot 或公开数据文件。

英文期刊检索结果如下：

- [Computers & Operations Research 2026 JD.com 论文](https://www.sciencedirect.com/science/article/abs/pii/S0305054825004034) 是本轮唯一找到“近期、中国业务、EV/TW、论文给出公开仓库入口”的强候选，但仍是单 depot，仓库和许可未验证。
- [Transportation Research Part C 2024：Pickup and delivery with EVs and TW considering queues](https://www.sciencedirect.com/science/article/pii/S0968090X24003504) 明确 EV、时间窗和队列，但页面只说明使用 benchmark instances，没有找到中国原始数据/公开文件。
- [Transportation Research Part B 2020：mobile battery swapping](https://www.sciencedirect.com/science/article/pii/S0191261520303593) 明确 EV/TW 和测试库，但不是中国、多 depot，且不是近三年公开中国数据。
- [European Journal of Operational Research 2017：electric location routing with TW and partial recharging](https://www.sciencedirect.com/science/article/pii/S0377221717300346) 有 EV、充电站和时间窗 benchmark，但不是中国多 depot 数据；页面没有给出本任务所需的中国公开实例包。
- [Computers & Operations Research 2022：branch-and-cut EVRPTW](https://www.sciencedirect.com/science/article/abs/pii/S0305054822001423) 和其他 TR-B/TR-C/EJOR 论文提供算法 benchmark 线索，但本轮没有验证到满足中国背景和四要素的公开再分发数据。

## 下载和文件结构抽查结果

用户要求对至多两个最有希望候选实际下载并抽查字段。本轮对重庆论文和 JD GitHub 入口做了实际访问尝试，但**没有源数据文件成功落盘**：重庆论文没有单独数据下载端点；JD 仓库访问受到当前环境的外部 DNS/网页授权限制。Zenodo/Figshare 的替代候选也只读到页面元数据，未把压缩包写入工作区。

为了保持可审计性，已建立探针目录：

`/Volumes/移动硬盘（512G）/ReSETP/baselines/e2_alns/china_open_instance_probe_20260717/`

目录内容：

- `README.md`：明确本目录不是源数据，不得作为优化输入。
- `download_attempts_20260717.md`：逐候选记录下载入口、已观察到的阻断和未完成状态。
- `verified_schema_snapshots_20260717.md`：只记录从已打开论文/页面实际看到的节点类别、规模和字段描述；明确哪些字段仍未验证。
- `checksums.sha256`：对上述三份记录文件绑定 SHA-256；该 manifest 不自哈希。

已绑定的 SHA-256 为：

```text
85d656d596eecb32937611c8112f1eb80bbb85be75ce7c9c0376871d855f5237  README.md
6da4c3063802e19b3d1d096aa66a75b22877c84fe2e220828d2e482de2b85f5b  download_attempts_20260717.md
58694b8a96a459c9b51f0f07fdb110b74240e5aa933c5814ae766da423c29681  verified_schema_snapshots_20260717.md
```

这意味着交付物 2 的“实际源文件下载与字段抽查”在本轮未完成；我没有用手工摘录文件冒充完成。若后续环境允许访问 GitHub/Zenodo，第一优先是下载并核验 JD 仓库和一个 Zenodo 结构化替代集，分别检查 `README/LICENSE`、客户/车场/充电站字段、坐标系、时间窗列、客户数和压缩包 SHA-256。

## 对 C31 的实际建议

当前最稳妥的路线是：以重庆论文作为业务锚点和“为什么要有多车场 + EV + 时间窗”的证据，按项目已有的北京/广东/重庆三地区域设计自行生成可复现的 50/100/200 客户数据；生成器必须把坐标、需求、时间窗、电池/能耗/充电站、车场归属和来源哈希写入同一份 metadata。JD 数据只有在仓库文件和许可证被实测确认后，才适合做外部现实性对照，不应先假定它可再分发。

本判决不触发任何优化实验，也不改变现有算法代码。

