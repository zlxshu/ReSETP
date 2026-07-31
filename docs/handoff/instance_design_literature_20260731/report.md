# 算例设计文献取证：多车场归属与非线性充电

- 任务编号：`INSTANCE-DESIGN-LITERATURE-20260731`
- 日期：2026-07-31
- 性质：**只读文献取证**。未改任何代码、算例、参数、论文、封存产物；未跑任何实验。
- 执行者：终端 Claude Code（Codex 配额耗尽至 2026-08-05 期间，用户逐任务授权 Claude 直接执行）
- 已读强制入口：`READ_ME_FIRST_FOR_AGENTS.md` / `CLAUDE.md` / `memory/MEMORY.md` /
  `memory/mechanism_condition_absent_20260731.md` / `mechanism_lever_rethink_20260731/report.md` /
  `memory/instance-lineage.md` / `memory/baseline-algorithm-catalog.md`
- 当前停止条件：本报告只给文献依据与选项清单，**不提出任何通过门、阈值、预注册要求或合格线**；
  改不改算例、改成什么，全部由用户裁决。

## 0. 口径说明（怎么读这份报告）

1. 每条结论标 **FACT**（读到的原文/数字）或 **INFERENCE**（我的解读或推算）。
2. **页码约定**：中文期刊与已定稿的英文期刊论文引用**印刷页码**（已逐篇用页眉/页脚核对偏移量）；
   预印本、网络首发、以文章号发表（无连续页码）的论文注明 **PDF 第 n 页**。每条引文都标了用的是哪种。
3. 引文一律短引：英文 ≤25 词，中文 ≤40 字。
4. 检索范围：本地 Zotero 库 `/Users/zhouleixishu/Zotero/`（1292 条目、423 个 storage 目录、
   396 个 PDF 附件），用 SQLite 元数据检索 + 逐页 `pdftotext` 定点核对。
   **本轮所有引用的数字都是从本地 PDF 原文逐句核对来的**，只有 1 篇是元数据/摘要级（见 §1）。
5. 拿不到出处的一律写"未找到"。没有出处的方向不写。

---

## 1. 文献清单与核对深度

| # | 论文 | Zotero key | 出处 | 核对深度 | 服务问题 |
|---|---|---|---|---|---|
| 1 | 王勇等 2023《资源共享模式下多中心共同配送电动车辆路径优化问题》 | ZKQ6DHPQ | 系统管理学报 32(6):1119–1141 | 本地全文，定点核对 | 1.1 / 1.2 / 1.3 |
| 2 | 陈雨蝶等 2023《"双碳"背景下联合配送冷链物流模型及其求解算法》 | W6UY6WKZ | **控制与决策 38(7)**，2023 年 7 月 | 本地全文，定点核对 | 1.1 / 1.2 / 1.3 |
| 3 | 陈雨蝶等 2025《双碳背景下复杂冷链物流模型及求解算法》 | 6KCQCP66 | 系统工程理论与实践（网络首发） | 本地全文，定点核对 | 1.1 / 1.2 / 1.3 |
| 4 | 陈婉茹等 2023《碳交易机制下多中心混合车队配送路径和速度优化研究》 | NKRC4JZU | 系统工程理论与实践 43(11):3320–3335 | 本地全文，定点核对 | 1.1 / 1.3 / 2.2 / 3 |
| 5 | 郑荣等 2023《"双碳"背景下多中心低碳冷链物流问题研究》 | EIU6WYTZ | 物流工程与管理 45(5) | 本地全文，定点核对 | 1.1 / 1.3 |
| 6 | Crevier, Cordeau & Laporte 2007 | NLUVLD2J | EJOR 176(2):756–773 | 本地全文，定点核对 | 1.1 / 1.3 / 1.4 |
| 7 | Dondo & Cerdá 2007 | 69I3U2RM | EJOR 176(3):1478–1507 | 本地全文，定点核对 | 1.1 |
| 8 | Sadati & Çatay 2021 | BPL6XIG5 | TR Part E（MDGVRP） | 本地全文，定点核对 | 1.1 |
| 9 | Soriano, Gansterer & Hartl 2023 | IF3WEZZJ | Int. J. Production Economics 255:108669 | 本地全文，定点核对 | 1.1 / 1.2 / 1.3 / **1.4** |
| 10 | Wang Y. et al. 2023 Collaborative MD-EVRPTW with shared CSs | 6Z9A3BFA | Expert Syst. Appl. 219:119654 | 本地全文，定点核对 | 1.1 / **1.2** / 1.3 |
| 11 | Wang Y. et al. 2024 Collaboration & resource sharing in MDTDVRPTW | 6JQKAQER | TR Part E 192:103798 | 本地全文，定点核对 | 1.1 / **1.2** / 1.3 |
| 12 | Montoya, Guéret, Mendoza & Villegas 2017 | GJB373Y4 | TR Part B（Article in Press） | 本地全文，定点核对 | 2.1 / 2.2 / 2.3 |
| 13 | Froger, Jabali, Mendoza & Laporte 2022 | PDVQ5Z86 | Transportation Science 56(2):460–482（HAL 预印本） | 本地全文，定点核对 | 2.1 / 2.2 / 2.3 |
| 14 | Keskin & Çatay 2016 | DLWIGJBK | TR Part C（Article in Press） | 本地全文，定点核对 | 2.1 / **2.2** / 2.3 / **2.4** |
| 15 | Schneider, Stenger & Goeke 2014 | JR544Q2D | Transportation Science（Articles in Advance, pp.1–21） | 本地全文，定点核对 | 2.1 / 2.2 |
| 16 | Hiermann, Puchinger, Ropke & Hartl 2016 | 7RM5SBIA | EJOR 252:995–1018 | 本地全文，定点核对 | 2.1 |
| 17 | Xiao, Zhang, Kaku, Kang & Pan 2021 | KGQ3LH89 | Renew. Sustain. Energy Rev. 151:111567 | 本地全文，定点核对 | 2.1 / **2.4** |
| 18 | Nafstad, Desaulniers & Stålhane 2025 | 9WS7JK73 | Transportation Science 59(3):628–646 | 本地全文，定点核对 | 2.1 / **2.3** / **2.4** |
| 19 | Zhen, Xu, Ma & Xiao 2020 | PVAZUJ4I | Int. J. Production Research | 本地全文，定点核对 | 2.1 |
| 20 | Vidal, Crainic, Gendreau & Prins 2014《Implicit depot assignments and rotations》 | MQZKQ5IK | EJOR 237(1):15–28 | **仅 Zotero 元数据 + 摘要**（本地无 PDF 附件） | 1.1 |

**本地全文核对 19 篇，仅摘要/元数据 1 篇。**

被检索到但本轮未展开的相关条目（本地有全文，留作后续）：
Londoño et al. 2023 [XQ82PJ6Y]、Wei et al. 2025 [BITGI54V]、Aghadavoudi Jolfaei & Alinaghian 2024 [NC5PBXQN]、
侯登凯等 2023 [A3FAGMZ4]、范厚明等 2022 [YGHSHVR9]、王兴义等 2018 [Y23T2NLP]、
Lee 2021 [E4G5Z2GB]、Karakatič 2021 [TALRNS4E]、Dönmez et al. 2022 [NQJWZWM9]、
Macrina et al. 2019 [494WILER/XV3EQNXK]、Wang & Zhao 2023 [MGIBNHAU]。
本地无附件的相关条目：Salhi/Imran/Wassan 2014 [Y2K7TEPR]、Wang et al. 2019 [SAYUKZY9]、
Li/Huang/Zhang 2026 [7UE6MB3W]（仅 HTML 快照）。

---

## 2. 第一组：多车场算例里客户归属怎么定（服务 E3）

### 2.1 问题 1.1：客户与车场的初始归属是怎么确定的

文献里有**两条互不相同的传统**，本项目当前的做法（按行政城市派生登记车场）落在两条之外。逐篇给出。

#### A. 国际 MDVRP 主流：**不预设归属，归属是决策变量**

**FACT（Vidal et al. 2014，EJOR 237(1):15–28，仅摘要核对）**：
摘要原句："The assignment choices … are thus no more addressed in the solution structure,
but implicitly determined during each move evaluation."
即车场选择被做成邻域移动评估时**隐式确定**的量，根本不进入解结构。

**FACT（Crevier et al. 2007，印刷第757页）**：综述前人 MDVRP 启发式时写明，
Renaud 等"an initial solution is built by first assigning every customer to its nearest depot"，
Cordeau 等"An initial solution is obtained by assigning each customer to its nearest depot"。
**最近车场只是构造初始解的手段**，随后"Improvements are performed by … relocating a
customer in a route incident to another depot"（同页），即客户可被移到别的车场的路线上。

**FACT（Crevier et al. 2007，印刷第761页）**：设计子问题域时写道，
"there is a high probability that in an optimal solution a customer will be served by its
nearest depot"。原文用的是"高概率"，**不是"必然"**。

**FACT（Sadati & Çatay 2021，MDGVRP，PDF 第4页）**：决策变量表里直接有
"1 if node i is visited by a vehicle assigned to depot j; 0 otherwise"；PDF 第5页约束说明
"a vehicle travels from a node to a depot or from a depot to a node only if that node is
assigned to that depot"。归属是模型内生的 0-1 变量。

**FACT（Dondo & Cerdá 2007，印刷第1478页摘要）**：其三阶段法里，
"a preprocessing stage clustering nodes together is initially performed to yield a more
compact cluster-based MILP problem formulation"，聚类的目的写明是**压缩 MILP 规模**，
随后"Phase II assigns clusters to vehicles"。聚类是算法手段，不是问题设定。

#### B. 中文共同配送传统：**先聚类定归属，再比较配送模式**

**FACT（王勇等 2023，印刷第1132页）**：算例为"重庆市主城区范围内的4个配送中心
(DC1~DC4)、146 个客户"；归属由 3D-K-means 时空聚类一次性确定——
"聚类后 DC1、DC2、DC3 和 DC4 分别服务33、33、42 和38 个客户"。
（表7 在印刷第1134页。）Case1–5 资源共享阶梯**在聚类之后**做，五个 Case 之间不重新聚类。
这一点已在 `mechanism_lever_rethink_20260731/report.md` 核实过，本轮复核一致。

**FACT（陈雨蝶等 2023，印刷第1957页 / 3.2.1节）**：
"在分区配送模式下，所有客户点分别划分至 4 个区域，每个配送中心只服务其所在区域的客户"；
联合配送模式下"各配送中心共享产品、客户、车辆等资源，共同服务所有客户"。
**分区档的归属是按区域外生给定的，联合档则完全放开。**

**FACT（陈雨蝶等 2025，PDF 第9页）**：解码规则是
"解码时根据载重限制将染色体划分为小路径，根据就近原则确定每条路径出发和返回的[配送中心]"。
即**就近原则用在解码阶段**（给已成形的小路径指派出发/返回中心），不是给客户贴一个登记标签。

**FACT（陈婉茹等 2023，印刷第3326页，3.3节初始解构造）**：
"第一阶段依据客户点到配送中心的距离聚类，将各客户点分配至最近的配送中心"。
但这是**初始解**；随后的邻域结构 N2/N4/N5（Inter swap、1-insert、2-insert，印刷第3326页）
在不同路径之间搬客户，而不同路径分属不同车场，因此归属在搜索中会变。

**FACT（郑荣等 2023，印刷第5–6页表2/表3）**：算例共 52 个节点，编号 1–48 为客户，
编号 49–52 需求为 0、时间窗为 [6,18]，即 4 个物流中心；表3 的 8 条路线分别起讫于
49/50/51/52。原文**没有给客户预设归属**，各中心服务谁由改进蚁群求解得出。
模型假设①（印刷第2页）只约束"冷藏车…均从配送中心出发，完成配送后返回原配送中心"。

**FACT（Wang Y. et al. 2023，PDF 第1–2页）**：用高斯混合聚类
"cluster customers and assign them to depots probabilistically to reduce the computational
complexity"；同时明确"which depot serves which customers are reallocated on the basis of
the optimization results"。聚类是**降复杂度手段**，归属最终由优化结果重分。

**FACT（Wang Y. et al. 2024，PDF 第9页）**：模型里有专门的重指派 0-1 变量
"δ_{i,d,d′} = 1, if customer i is reassigned from DC d to d′"。

**FACT（Soriano et al. 2023，PDF 第4页）**：这是本轮唯一一篇**把"登记归属"写进问题定义**的：
"In the stand-alone situation, customer i ∈ C is assigned to depot d_i"。
单干情形下每个客户有一个归属车场 d_i，联盟优化后可以换。

#### 小结（INFERENCE）

- 国际 MDVRP 主流不设初始归属，"最近车场"只作构造初始解或缩小子问题的启发式，**优化后归属可变**。
- 中文共同配送流派普遍用**聚类**（K-means / 3D-K-means / 高斯混合 / 谱聚类 / 距离最近）确定归属，
  聚类的目的一律写作降低多中心问题复杂度或构造初始解，不是"这就是企业的真实登记关系"。
- **按行政区划派生归属（本项目 `china81.py:355` 的"客户所在城市 → 该城市唯一车场"）在本轮检索到的
  全部 11 篇多车场论文里都没有先例**。最接近的是陈雨蝶 2023 的"划分至 4 个区域"，但那是
  为了构造"分区配送"这一档**对照臂**而人为划的区，不是数据的固有属性。
- 只有 Soriano et al. 2023 明确把"单干时的登记归属 d_i"当成问题输入，而它的算例是人工生成的
  （见 2.4）。

### 2.2 问题 1.2：文献里有没有"归属错配"这个概念

**有，而且被明确当成待纠正的问题来研究，但用的是别的术语。** 逐条给出。

#### 找到的三处

**FACT（Wang Y. et al. 2024，PDF 第22页，图9 的文字解释）**：
"Some customers that are spatially far away from their initial DC are reassigned to a new
closer DC."
这就是"登记在 A 场但更适合由 B 场服务"的字面表述。同页还写
"The customers that have similar distances from several different DCs are reasonably
assigned to one of them with the consideration of customers' time windows."
另在 PDF 第7页把未优化网络的问题归因于
"inadequate service range of DCs, suboptimal travel sequences, inefficient vehicle scheduling"。

**它怎么量化错配的比例**（FACT，PDF 第28页表14，重庆 5 个 DC / 136 客户）：

| 情形 | 各 DC 客户数 | TOC ($) | 车辆数 | 碳排 (kg) |
|---|---|---|---|---|
| 不协同、不共享 | 33 / 28 / 23 / 25 / 27 | 7,078 | 24 | 387.66 |
| **协同（客户重指派）、不共享车辆** | 21 / 27 / 41 / 18 / 29 | **4,640** | 18 | — |
| 协同 + 车辆共享 | 21 / 27 / 41 / 18 / 29 | 3,598 | 10 | 200.87 |

各 DC 客户数净变化 −12 / −1 / +18 / −7 / +2，**至少 20 个客户（≥14.7%）换了车场**（INFERENCE：
这是从两行客户数之差推的净流动下界，原文没有直接给"改变归属的客户数"）。
效应量（FACT）：只做客户重指派、不共享车辆，总成本从 $7,078 降到 $4,640，降 **34.4%**；
再加车辆共享降到 $3,598，相对前一档再降 **22.5%**（INFERENCE：两个百分比由表内数字直接相除得到，
原文没有以百分比形式写出）。
**这是本轮检索到的唯一一篇把"客户重指派"和"车辆共享"分成两档单独测的论文。**

**跨场调拨成本口径（对本项目直接相关）**：表14 里"不协同"行的 CTC 列为 **0**，两个协同行均为 **233**。
**FACT（PDF 第10页，式(9)）**："the CTC represents the centralized transportation cost of
semitrailers among DCs"，即用半挂车在各 DC 之间调拨货物的集中运输成本，且它是目标函数
Z1 = CTC + OC + SC + PCW + PCD 的组成项。
**INFERENCE**：上面那 34.4% 是**已经扣掉 $233 跨场调拨成本之后**的净收益。
本项目按 2026-07-12 用户裁决把 c^tr 设为 0，与这篇对照存在口径差异，引用时须交代。

**FACT（Wang Y. et al. 2023，PDF 第18–19页，重庆 4 个 depot / 143 客户）**：
"The reallocation of customer service has changed the affiliation between customers and depots.
In Table 16, the service relationship of 22 customers has been changed"。
即 **22 / 143 = 15.4% 的客户改变了归属**（INFERENCE：百分比是我算的）。
重指派后各 depot 客户数为 34 / 42 / 40 / 27（PDF 第19页）。

**FACT（Soriano et al. 2023，PDF 第9页）**：报告了一个直接的错配/搬迁度量
"the rate of original customers kept"（保留原有客户的比例），
"with rates of even 100% … for some partner in a 2D_100C instance. When instance sizes get
larger, the rate tends to decrease, with minimums of even 0% (no original customer kept)"。
比例范围 0%–100%，随算例规模变大而下降。

#### 与本项目直接相关的一条对照（FACT，Soriano et al. 2023，PDF 第7页）

原文解释为什么**聚集型算例**里协同没什么可捞：
"On C_B instances … costs are seemingly lower since all customers are served from the depot
nearest to them. Consequently, all partners in S⁻ will already have high profit change rates …
leaving little room for improvement on the fairness objective."

**INFERENCE**：这句话描述的正是本项目 E3 的处境——当每个客户本来就由最近车场服务时，
协同优化的可改进空间本来就小。这是文献里对"错配率为零 → 协同收益很小"这一因果关系的直接表述。

#### 未在文献中找到的部分

**未找到**：任何一篇论文用"错配率"（mismatch rate / misassignment rate）作为**算例设计的
预设指标**，或者报告"我们构造了错配率为 X% 的算例"。文献里的比例都是**优化结果的事后统计**
（多少客户被重指派），不是算例的入参。

#### 跨场协同的收益在文献里通常被归因于什么

| 论文 | 归因（FACT 原文） | 出处 |
|---|---|---|
| 王勇等 2023 | "通过多中心间资源共享使电动车使用数减少了56.0%…运营成本降低了43.2%"；车队从各中心固定变为全局共享池 | 印刷第1133页 |
| 陈雨蝶等 2023 | "分区配送并没有共享配送中心的客户和车辆资源，易造成车辆装载率低" | 印刷第1957页 |
| 陈雨蝶等 2025 | "独立配送客户点位置十分分散…分区配送客户点比较集中，联合配送模式共享产品、客户、车辆等社会资源" | PDF 第17页 |
| Wang et al. 2023 | 客户服务重分配 + 充电站共享（5 个 CS 被跨 depot 共享，省下 3 个 CS） | PDF 第18、21页 |
| Wang et al. 2024 | 客户重指派（缩短配送距离、减少时间窗违反）+ 车辆共享（6 辆车跨中心共享，省 $600 租赁费） | PDF 第26页 |
| Soriano et al. 2023 | 联盟集中优化降低总成本，但会造成收益分配剧烈变化 | PDF 第1–2页 |

**INFERENCE**：归因主要落在三个渠道——**客户重指派（空间分工重划）**、**车队/车辆池化**、
**充电或其他设施共享**。Wang et al. 2024 是唯一把前两者分档隔离测量的；
王勇 2023 隔离的是后两者（客户归属聚类前已固定）；陈雨蝶两篇把渠道混在一起。

### 2.3 问题 1.3：这些论文的算例规模

| 论文 | 车场数 | 客户数 | 客户分布 | 车场:客户 | 出处 |
|---|---|---|---|---|---|
| 王勇等 2023 | 4 | 146 | 重庆主城区真实地理坐标 | 1:36.5 | 印刷第1132页 |
| 陈雨蝶等 2025 | 4（D36–D39） | 36（0–35） | 广州，人工坐标表 | 1:9 | PDF 第11页 |
| 陈雨蝶等 2023 | 4（D36–D39） | 表3 给定坐标 | 人工坐标表，"划分至 4 个区域" | — | 印刷第1956–1957页 |
| 陈婉茹等 2023（仿真） | 6 | 71（步步高超市配送点） | 长-株-潭真实地理 | 1:11.8 | 印刷第3330页 |
| 陈婉茹等 2023（基准） | 4 或 6 | 48 / 72 / 96 / 144 / 192 / 216 / 240 / 288 | Cordeau MDVRPTW Pr01–Pr20 | 1:12 ~ 1:72 | 印刷第3329页表5 |
| 郑荣等 2023 | 4（节点49–52） | 48 | 人工坐标表 | 1:12 | 印刷第5页表2 |
| Crevier et al. 2007 | 3 / 4 / 5 / 6（r 列） | 48 / 72 / 96 / 144 / 192 / 216 | 见下方生成配方 | 1:12 ~ 1:64 | 印刷第768页表5 |
| Soriano et al. 2023 | 2 / 3 / 4 | 100 / 150 / 200 | clustered vs. uniform 两类 | 1:50 | PDF 第7页 |
| Wang et al. 2023（案例） | 4 | 143 | 重庆真实地理 | 1:35.8 | PDF 第17页 |
| Wang et al. 2023（基准） | 见 NEO MDVRPTW 库 | 例如 Instance 1 有 48 客户 | Cordeau 系 | — | PDF 第17页 |
| Wang et al. 2024（案例） | 5 | 136 | 重庆核心城区真实地理 | 1:27.2 | PDF 第21页 |
| Montoya et al. 2017 | 1（单车场 + 充电站） | 10 / 20 / 40 / 80 / 160 / 320 | uniform / clustered / 混合，120×120 km | — | PDF 第13页 |

**FACT（陈婉茹等 2023，印刷第3329页表5）**：Cordeau MDVRPTW 基准集 Pr01–Pr20 的 n/d 完整清单为
48/4、96/4、144/4、192/4、240/4、288/4、72/6、144/6、216/6、288/6，再重复一遍（Pr11–Pr20）。
即 **4 或 6 个车场，48–288 个客户**。

**INFERENCE**：把本项目的 2 车场 / 50 客户与 2 车场 / 100 客户放进这张表，
车场数是所有对照里**最少的**（并列最少的是 Soriano 的 2D_100C 一档），
车场:客户比 1:25 与 1:50 落在中间偏密集一侧。参考母版（王勇、陈雨蝶两篇、郑荣）都是 4 个中心，
陈婉茹是 6 个中心（仿真）或 4/6（基准）。

### 2.4 问题 1.4：有没有可直接引用的"制造错配"的算例构造方法

**有两条**，都来自本地全文。

#### 方法一：Soriano et al. 2023 的 clustered / uniform 双类构造

**FACT（PDF 第7页，5.2 Data description）**：
"we differentiate between two types of customer locations (clustered vs. uniform) and two types
of initial revenue share distribution (balanced vs. unbalanced). In clustered instances customers
are placed closer to the depots of the carriers, while being randomly located in the uniform type."

四类编码 C_B、C_U、U_B、U_U，每类三个规模：2D_100C（2 车场 100 客户）、3D_150C、4D_200C。
所有客户需求相同（10）、收入相同（100）。
**FACT（同页）**：全部生成算例已公开发布——"All generated instances can be found in
Soriano et al. (2020)."

**FACT（PDF 第4页）**：单干情形下每个客户有登记车场 d_i；单干解 S⁰ 的各车场利润 P_d⁰
是模型的外生输入参数。

**FACT（PDF 第7页）**：原文自己对比了两类的效果——聚集类（C_B）里
"all customers are served from the depot nearest to them"，因而"leaving little room for
improvement"；均匀类（U_U）里客户随机落点，重指派幅度大到
"maximums between 300% and 400%"（各伙伴工作量变化率，PDF 第9页）。

**INFERENCE**：这是本轮找到的**唯一一条"错配有无"被当成算例设计维度、并且两档都跑了、
两档结果差异被原文解释过**的构造方法。要造出"确实存在归属错配"的算例，
uniform 档（客户随机落点、登记归属按单干情形给定）是有出处可直接引用的做法。

#### 方法二：Cordeau/Crevier 的 β 参数（控制客户围绕车场聚集的紧密程度）

**FACT（Crevier et al. 2007，印刷第767页，4.2 节）**，逐字生成步骤：
1. "Randomly generate r − 1 depots in the [−50, 50] × [−50, 50] domain."
2. 客户 i 的坐标在 [−100, 100] × [−100, 100] 域内随机生成；
3. "Let u be a random number selected in the [0,1] interval and U the distance between customer i
   and its closest depot. If u < e^{−βU}, set i := i + 1."
4. "In this procedure, β controls the compactness of the customer clusters. This parameter was
   fixed at 0.05."

**FACT**：车场生成在 [−50,50]²，客户生成在 [−100,100]²，即**客户的分布域是车场分布域的两倍宽**。
接受概率 e^{−βU} 只与"到最近车场的距离"有关，因此这套配方里**根本不存在"登记车场"这个字段**，
只有"最近车场"。

**INFERENCE**：β 是一个有出处的、连续可调的"聚集紧密程度"旋钮（β 越小客户越发散）。
但它调的是**几何聚集度**，不是"登记归属与最近车场之差"——要用它造错配，仍需另行规定
登记归属怎么给，而**这一步文献里未找到**。

#### 未找到的部分

**未找到**：任何论文给出"先按规则 X 指定登记车场、再按规则 Y 移动客户位置，使错配率达到 Z%"
这类显式的错配构造算法。文献里错配要么是真实案例数据自带的现状（Wang et al. 2023 / 2024 的
重庆案例——**两篇都没有说明案例中"初始归属"是怎么来的，只说是真实配送网络的现状服务关系**），
要么是随机布点后由单干解隐含决定（Soriano et al. 2023）。

---

## 3. 第二组：非线性充电在什么条件下才影响决策（服务 E5）

### 3.1 问题 2.1：参数对照表

| 论文 | 电池容量 | 充电功率 | 等效倍率（INFERENCE，原文均未给 C 数） | 里程 / 时长约束 | 时间窗 | 出处 |
|---|---|---|---|---|---|---|
| Montoya et al. 2017 | **16 kWh**（Peugeot iOn，0.125 kWh/km） | **11 / 22 / 44 kW** 三档（slow / moderate / fast） | 0.69C / 1.375C / 2.75C | 客户落在 **120×120 km** 区域；**最大路线时长 10 h**；满充理论续航 128 km（16÷0.125，原文未直接写这个数） | **无客户时间窗**，只有最大路线时长 | PDF 第4、13页 |
| Froger et al. 2022 | 同上（直接继承 Montoya 的 120 算例） | 同上 | 同上 | 同上 | 同上；新增每 CS **1 或 2 把充电枪** | PDF 第22页 |
| Nafstad et al. 2025 | 取自 Desaulniers et al. 2016 算例（正文**未给 kWh 数值**） | 44 / 22 / 11 kW 三档（照 Montoya 的三条曲线按电池维度缩放） | 未给 | Solomon 系，25 / 50 / 100 客户；21 个充电站 | **type 1 窄时间窗 / type 2 宽时间窗**（关键分档） | 印刷第639页 |
| Schneider et al. 2014 | **不以 kWh 计**：取 max{对应 VRPTW 最优解平均路线长度 60% 所需电量, 2×最长"客户–站"弧电量}；能耗率 h 设为 1.0 | 充满一次 = 该算例**平均客户服务时间的 3 倍** | 不适用 | Solomon 100 客户改造；**车场处设 1 个充电站**，另 20 个随机布点 | 因绕行充电导致原 Solomon 时间窗不可行，故**重新生成时间窗** | 印刷第12页 |
| Keskin & Çatay 2016 | 沿用 Schneider 2014 算例 | 沿用 | — | 同上 | 同上；分 type-1 / type-2 | PDF 第4、11页 |
| Hiermann et al. 2016 | 以 Schneider 的 Y 为基值，**按车型档位缩放**（原文未给 kWh） | 能耗率与充电率"directly taken from the instances of Schneider et al. (2014)"，各车型相同 | — | Solomon C/R/RC × 1/2 | Solomon | 印刷第1006页 |
| Xiao et al. 2021 | **16 / 20 / 24 / 32 kWh**（专门的容量敏感性四档） | 正文**未核到明确 kW 数值**（用非线性充电函数，参数取自 Xiao et al. 2019） | — | Solomon R1/C1/RC1 前 11 个客户 + 1 个中心；车队 5 辆 EV | Solomon | PDF 第15、18页 |
| Zhen et al. 2020 | 示例中 **20 kW·h**（混动车，另带 20 加仑油箱） | 到充电站**充满**（"recharged fully when the HEV visits a charging station"） | — | 5 / 8 / 10 / 20 / 50 客户人工算例 | — | PDF 第4、7、11页 |
| 陈婉茹等 2023 | **80 kW·h**（表7"电池容量 B"） | **未建模**（离场前充满、途中不充） | — | **车辆最大行程时间 8 小时**；速度下限 30 / 上限 60 km/h | 有客户时间窗 | 印刷第3330页表7 |
| Wang Y. et al. 2023 | **60 kWh** | **30 kWh/h** | 0.5C | **最大行驶距离 100 km**；SOC 下限 25% | 有客户时间窗 | PDF 第19页表14 |

补充两条 FACT：

- Montoya et al. 2017（PDF 第4页）：三条分段线性曲线是拟合 Uhrig et al. (2015) 的实测数据，
  "average relative absolute error of 0.90%, 1.24%, and 1.90% for CSs of 11, 22, and 44 kW"。
- Montoya et al. 2017（PDF 第1页，引言）："For the most common EVs used in service operations,
  the minimum charging time is 0.5 h and the battery capacity is around 22 kWh."
  这是原文对"服务运营常用 EV"的行业描述，不是它算例的取值。

### 3.2 问题 2.2：充电发生在什么时候，到站/离站 SOC 是多少

#### 结论先行（INFERENCE）

本轮核对的**每一篇**非线性/部分充电文献都假定**车辆离开车场时电池是满的**，
所有被建模的充电决策都发生在**途中充电站**。"车场行前从 0% 充到够用"这种模式，
在这批文献里**没有对应物**——不是被认为不好，而是压根不是它们建模的对象。

#### 逐篇 FACT

**Montoya et al. 2017（PDF 第4页）**：
"It is assumed that the EVs leave the depot with a fully charged battery."

**Froger et al. 2022（PDF 第10页）**：
"Constraints (8) state that every EV leaves the depot with a fully charged battery."

**Keskin & Çatay 2016（PDF 第3页）**：
"Unlike EVRPTW where the vehicle departs from the depot/station with full battery … in
EVRPTW-PR the vehicle departs from the depot fully charged but may arrive at/depart from a
station with any state of charge and it returns to depot with an empty battery if it has been
recharged once during its route."

**Keskin & Çatay 2016，命题 1 及其证明（PDF 第5页）——本条对 E5 最关键**：
"Proposition 1. If an optimal solution exists such that an EV leaves the depot with its battery
partially charged, i.e. Y₀ < 1, then the same EV departing from the depot fully charged is also
optimal."
证明原句："Since fully recharging the battery at the depot does not delay the departure time of
the EV, Y₀ = 1 must also be optimal."

**INFERENCE**：这条命题的前提是**车场充电不占用运营时间**。也就是说，文献本身就认定
"行前在车场充电"这件事**在时间维度上是免费的、没有决策含量的**，所以才可以无损地假定充满。
本项目 E5 观察到的"196 个会话里 140 个在第 0 秒起充、非线性只改变时长、不改变任何决策、
成本效应 0.000%"，与这条命题的结论完全一致——**在文献的建模框架里这本来就是预期结果**。

**Schneider et al. 2014（印刷第12页）**：车场处设一个充电站——
"We locate one recharging station at the depot because a recharging possibility at the depot
seems to be a reasonable claim."
但充电站处**一律充满**（印刷第5页）："the difference between the present charge level and the
battery capacity Q is recharged with a recharging rate of g"。

**Schneider et al. 2014（印刷第5页）——线性假设的自陈**：
"For simplification reasons, we assume a linear recharge, although in real-world recharging
processes the charging time increases for the last 10%–20% of the battery capacity
(Marra et al. 2012)."

**陈婉茹等 2023（印刷第3322页，2.1 问题描述）**：
"电动车电池容量已知，且在离开配送中心前充满电，在途中不充电。"
这是本轮唯一一篇采取"行前在场充满、途中完全不充"设定的论文，
但它**同时完全不建模充电时长**（模型里只有约束(21)"电动车配送过程中消耗的电能不超过电池容量"）。

**Zhen et al. 2020（PDF 第4页）**："Each HEV has a full battery and gasoline tank before
departure. The HEV will be recharged fully when the HEV visits a charging station."

**Froger et al. 2022（PDF 第24页）——唯一放开车场出发时刻的一篇**：
在充电桩容量受限时，"it is sufficient to make the EVs leave the depot after time 0, as is done
in version D"。即把"延后出发时刻"当成缓解充电排队的一个决策手段。

#### 到站 / 离站 SOC 的实测统计

**Montoya et al. 2017（PDF 第17–18页，图12）**——本轮唯一给出 SOC 分布统计的一篇：
- "over 90% of the mid-route charges are partial charges (i.e., they do not fully charge the
  battery)."
- "the percentage (around 12%) of mid-route charges that restore the battery to above 80% of
  its capacity."
- "a common assumption in the E-VRP literature is that the battery can be charged only in the
  linear segment of the charging curve (which ends at roughly 80% of the capacity). Our data
  suggests that good E-VRP-NL solutions often include routes with mid-route charges that take
  the battery level into the nonlinear part of the charging function."

**到站 SOC**：**未找到**。Montoya 只报告了充电**之后**的电量分布（图12），没有报告到站时的 SOC 分布。
其余各篇也没有。

**每条路线的充电次数**（FACT，Nafstad et al. 2025，印刷第639页）：
"The average number of recharging operations per route is approximately 1.10 in the results
reported by Desaulniers et al. (2016) and 1.02 in the results reported by Montoya et al. (2017)."
Montoya 自己另报（PDF 第17页）："85.83% of the solutions contain at least one route with more
than one mid-route charge"。

### 3.3 问题 2.3：文献怎么论证非线性建模是必要的，差异有多大

#### Montoya et al. 2017：四种充电函数近似的对照实验（PDF 第14–15页）

对 20 个算例分别用 FS（只允许充到 80%，回避非线性段）、L1（乐观线性）、L2（悲观线性）、
PL（分段线性，即本文的非线性近似）求最优解并互相评估。

| 近似 | 报告的后果（FACT 原文） |
|---|---|
| FS | "in 3 of the 20 instances the FS approximation increases the number of routes"；"9 instances become infeasible with the FS approximation"；"are (on average) **2.70% more expensive**" |
| L1（乐观） | "for 14 instances, the L1 solutions are infeasible in practice" |
| L2（悲观） | "L2 leads to solutions that are (on average) **1.45% more expensive**, and it increases the number of routes in two instances" |

**FACT（PDF 第14页）**，原文自己给出的机制解释：
"Because the maximum route duration is limited, the time spent detouring and recharging the
battery reduces the number of customers that can be visited."
即卡点是**最大路线时长（10 h）与电池容量共同作用**，充电时间与配送时间抢同一份预算。

#### Froger et al. 2022：充电桩数量比充电曲线本身更 binding（PDF 第3页）

"55 of the BKSs become infeasible if there is only one charger per CS. This figure drops to 23
and three for the cases with two and three chargers."

#### Nafstad et al. 2025：线性简化改变的是**解的结构**（印刷第644页）

- "in almost 80% of the instances where the simplifications give infeasible solutions,
  (some of) the routes serve different customers."
- "on average, more than 10% of the customers have moved to a different route, which means that
  for an instance with 100 customers, more than 10 customers are served by a different route."
- "This clearly indicates that the structure of the solutions can change significantly when the
  recharging model is simplified."

同时，原文对**目标值差异**的报告要小得多（印刷第643页，表6，type 2 宽时间窗算例）：
"the objective values for the type 2 instances only increase for the L1 secant and L3 secant
simplifications, where the maximum increases are 0.02% and 1.42%, respectively."

#### 指标归纳（INFERENCE）

文献用来论证非线性必要性的指标，按被报告的频次排序：
**① 可行性**（Montoya 9/20 不可行、L1 14 个不可行；Froger 55/120 不可行）→
**② 解的结构 / 客户在路线间的分配**（Nafstad：80% / >10% 客户换路线）→
**③ 车辆数**（Montoya 3/20 增加路线数）→
**④ 成本**（2.70% / 1.45% / 最高 1.42%，量级最小）。
**成本差异是这批文献里最小的一项指标**，可行性和结构差异才是主证据。

### 3.4 问题 2.4：让非线性真正影响决策，文献支持哪些方向

只列**有出处**的方向。每条给论文、原文、页码，以及原文报告的效应指标。不做取舍、不排优先级。

#### 方向 A：收紧时间窗 / 压缩可用时间（两篇独立支持）

**FACT（Nafstad et al. 2025，印刷第643页）**：
"if the instances that one faces have wide time windows, there is little benefit of solving the
problem with heterogeneous nonlinear recharging functions as a simplification might give an
equally good outcome at a lower computational cost and less implementation effort."
即**宽时间窗下非线性建模没什么价值**；反过来，其 type-1（窄时间窗）算例才是差异出现的地方。

**FACT（Keskin & Çatay 2016，PDF 第15页）**：
"When q is free the average improvement in total distance is 2.89% in type-1 problems whereas
the average improvement in type-2 problems is only 0.66%."
以及："these results suggest the PR scheme is effective, particularly in cases where the time
windows are more restrictive."
同页解释："PR has more potential for saving from the number of vehicles in type-1 problems,
which is an expected outcome since those problems are more restrictive due to narrow
time-windows and shorter route durations."

**FACT（Montoya et al. 2017，PDF 第14页）**：
"Because the maximum route duration is limited, the time spent detouring and recharging the
battery reduces the number of customers that can be visited."
其算例的时长上限为 10 h（PDF 第13页）。

#### 方向 B：把充电放进与其他资源竞争的时段（一篇支持）

**FACT（Froger et al. 2022，PDF 第3页）**：给每个充电站设 1 或 2 把充电枪后，
120 个已知最优解中 55 个变得不可行（1 把枪）、23 个不可行（2 把枪）。
**FACT（PDF 第24页）**：他们用"延后车场出发时刻"（version D）作为缓解手段之一。

**FACT（Keskin & Çatay 2016，PDF 第5页命题1）**：反向证据——
只要"fully recharging the battery at the depot does not delay the departure time of the EV"，
车场充电就没有决策含量。

#### 方向 C：降低充电功率档位（一篇给出可直接引用的档位）

**FACT（Montoya et al. 2017，PDF 第4页）**：11 / 22 / 44 kW 三档，均由 Uhrig et al. (2015)
实测数据拟合，拟合误差 0.90% / 1.24% / 1.90%。
**FACT（Nafstad et al. 2025，印刷第639页）**：沿用同一套 fast / normal / slow = 44 / 22 / 11 kW
的映射，并按各算例电池容量在电量维度上缩放。

（说明：这两篇给的是**充电功率档位的文献取值**，**未找到**任何一篇论文报告"把功率从 22 kW
降到 11 kW 会让非线性折减区被触发多少"这类定量关系。）

#### 方向 D：把电池容量当作敏感性轴（一篇支持，且方向与"变大"相反）

**FACT（Xiao et al. 2021，PDF 第18页，6.3 节"Experiments on the effect of battery capacity"）**：
"The battery of EVs was set to take capacities of 16, 20, 24, and 32 kW-h (with the same the
fixed cost), respectively."
结果："A higher battery capacity setting, i.e., 32 kW-h, has always resulted in solutions with
lower objective values (total costs) … with average cost deviations of 21.23 %, 9.73 %, 1.70 %,
and 0.19 % corresponding to the battery capacities of 16, 20, and 24 kW-h, respectively."
机制解释（同页）："a battery with a lower capacity often prompts the driver to take detours to
CSs, consequently increasing the total distance and total time."

**INFERENCE**：这条支持的是"**把电池容量做成敏感性维度**"这个操作本身有先例，
而且其证据方向是**容量越小、充电对成本的影响越大**。
**未找到**任何论文以"故意调大电池容量以触发非线性"为方向。

#### 方向 E：算例的地理尺度与路线时长设定（一篇给出可直接引用的配方）

**FACT（Montoya et al. 2017，PDF 第13页）**：
"We located the customers in a geographic space of 120 × 120 km using either a random uniform
distribution, a random clustered distribution, or a mixture of both. Our main motivation for
choosing the 120 × 120 km area was to build instances representing a semi-urban operation."
以及："we set the maximum route duration for every instance to 10 h."
120 个算例已公开发布于 www.vrp-rep.org（数据集编号 VRP-REP:2016-0020）。

#### 未找到出处的方向（因此不写成方向）

- **改成"SOC 降到某阈值以下才触发充电"的规则式策略**：**未找到**。
  本轮核对的所有非线性充电论文中，充电量与充电地点都是路径优化的决策变量
  （Montoya PDF 第4页变量 q_i / o_i / s_i / d_i；Keskin & Çatay PDF 第4页决策变量 Y_i），
  不是阈值触发的规则。
- **提高单日里程以迫使深度充电**：**未找到**直接以"提高里程 → 非线性 binding"为论证的论文。
  最接近的是方向 E（更大的地理范围 + 时长上限），以及 Xiao 的"容量小 → 绕行去充电站变多"，
  但两者都不是"提高里程"这个操作本身的出处。

---

## 4. 第三组：本项目当前参数在文献取值区间里的位置

只做定位，不给"应该改成多少"。

### 4.1 本项目当前设定（本轮从仓库代码/数据核对的 FACT）

| 项 | 取值 | 来源 |
|---|---|---|
| 车场数 | **2**（D_guangzhou / D_shenzhen） | `data/ChinaInstances/china81_stage2_static_inputs_corrected_v3_20260723/instances/cn-prd-50c-01-V2-LOCATIONS/nodes.csv`：2 depot + 2 station + 50 customer |
| 客户数 | 50（`cn-prd-50c-01`）/ 100（`cn-prd-100c-02`） | 同上；及 `memory/mechanism_condition_absent_20260731.md` |
| EV 电池容量 | **77.28 kWh** | `solver/src/setp_solver/china81.py:672`（`battery_kwh=77.28`）、`:893`（`B_battery_kwh=77.28`） |
| 车场充电功率 | **22.0 kW** | `solver/src/setp_solver/china81.py:905`（`depot_charge_power_kw=22.0`） |
| EV 初始电量 | **0.0 kWh** | `solver/src/setp_solver/china81.py:894`（`initial_ev_battery_kwh=0.0`） |
| 充电策略 | 车场行前充电 + 趟间按需补电 | 任务背景（已核实事实） |
| 运营时域 | 06:00–22:00（16 h） | 任务背景（已核实事实） |
| 登记车场派生规则 | 客户所在城市 → 该城市唯一车场 | `solver/src/setp_solver/china81.py:355` |
| 实测错配率 | 0 / 150 | `e3_zone_joint_20260731/input_assignments.csv` |
| 实测终止 SOC | 中位 37.03% / 均值 46.95%；100% 者 36/196 | `e5_nonlinear_final_20260730/charging_sessions.csv` |

### 4.2 逐项定位

**① 车场数 = 2**
- 文献区间：中文母版 4（王勇、陈雨蝶×2、郑荣）或 6（陈婉茹仿真）；
  Cordeau MDVRPTW 基准 4 或 6；Crevier 生成算例 3–6；Soriano 2–4；Wang 案例 4 与 5。
- 定位：**处在区间下界**。仅与 Soriano 的 2D_100C 一档并列最少。
  参考母版全部 ≥4。（FACT + INFERENCE）

**② 车场:客户 = 1:25（50c）/ 1:50（100c）**
- 文献区间：1:9（陈雨蝶2025）到 1:72（Cordeau Pr06/Pr16）；中文母版案例集中在 1:12 ~ 1:36。
- 定位：**落在常见区间内**，偏稀疏一侧。（INFERENCE）

**③ 客户登记归属 = 按行政城市派生**
- 文献做法：不预设归属（国际主流）、聚类确定（中文流派）、真实案例现状（Wang×2）、
  人工生成 + 单干解隐含（Soriano）。
- 定位：**本轮 11 篇多车场论文中未找到同类做法**。
  它的直接后果——错配率按构造恒为零——正是 Soriano 的 C_B（聚集平衡）档所描述的
  "all customers are served from the depot nearest to them … leaving little room for
  improvement"（PDF 第7页）。（FACT + INFERENCE）

**④ 电池容量 = 77.28 kWh**
- 文献取值：16 kWh（Montoya / Froger，Peugeot iOn 城市小车）；16/20/24/32 kWh
  （Xiao 敏感性四档）；20 kW·h（Zhen 示例）；60 kWh（Wang et al. 2023）；
  **80 kW·h（陈婉茹等 2023 表7）**；Schneider / Keskin / Hiermann / Nafstad 均不以 kWh 计。
- 定位：**在纯 EVRP 非线性充电文献（Montoya 系）里偏高约 4.8 倍；
  在中国多中心混合车队文献里几乎正中**——陈婉茹的 80 kW·h 与本项目的 77.28 kWh 相差 3.4%，
  Wang et al. 2023 的 60 kWh 也是同一量级。（FACT + INFERENCE）
- 附注（更正）：`mechanism_lever_rethink_20260731/report.md` §3.3 用 16 kWh 单一对照得出
  "本项目约为文献的 4.83 倍"。这个倍数对 Montoya/Froger 成立，但把对照面扩到
  陈婉茹（80 kW·h）与 Wang et al. 2023（60 kWh）后，77.28 kWh 落在**区间之内**。

**⑤ 充电功率 = 22 kW（车场）**
- 文献取值：11 / 22 / 44 kW（Montoya、Froger、Nafstad 三档）；30 kWh/h（Wang et al. 2023）；
  Schneider 系用"充满 = 3×平均服务时间"（无 kW）；陈婉茹不建模充电时长。
- 定位：**正好等于文献三档中的中档（moderate）**，是快充档（44 kW）的一半。（FACT）

**⑥ 等效倍率 = 22 ÷ 77.28 ≈ 0.28C（INFERENCE，原文均不报 C 数）**
- 文献对照（同为 INFERENCE 推算）：Montoya 三档 = 0.69C / 1.375C / 2.75C；
  Wang et al. 2023 = 30÷60 = 0.5C。
- 定位：**低于本轮核到的所有报了 kWh 与 kW 的文献**。最接近的 Wang et al. 2023 是它的约 1.8 倍。

**⑦ EV 初始电量 = 0.0 kWh，行前从 0% 起充**
- 文献做法：Montoya、Froger、Keskin & Çatay、Zhen、陈婉茹**全部**假定车辆离场时电池满电；
  Schneider 在车场设充电站但充电站一律充满。
- 定位：**本轮核对的全部文献中未找到同类设定**。
  Keskin & Çatay 命题 1（PDF 第5页）从相反方向给出了这个设定的性质：
  只要车场充电不推迟出发时刻，行前充满就是无损的最优选择——
  也就是说**这个环节在文献框架里被认定为没有决策含量**。（FACT + INFERENCE）

**⑧ 充电时机：140/196 会话起充于第 0 秒（车场行前），运营时域 06:00 才开始**
- 文献做法：所有被建模的充电决策都在途中充电站；只有 Froger 的 version D
  把"延后车场出发时刻"当决策（PDF 第24页）。
- 定位：**本项目的充电绝大多数发生在与任何稀缺资源都不竞争的时段，
  文献里没有对应的建模对象**。（FACT + INFERENCE）

**⑨ 终止 SOC：中位 37.03% / 均值 46.95%，仅 36/196 达 100%**
- 文献对照：Montoya 实测最优解中"over 90% of the mid-route charges are partial charges"，
  且"around 12%"的中途充电把电量补到 80% 以上（PDF 第17–18页）。
- 定位（分两条，不能合并）：
  - **部分充电占绝大多数这一点与文献一致**——Montoya 的"90%+ 为部分充电"与本项目
    "196 个会话中 160 个终止 SOC 未达 100%"同向。（FACT）
  - **进入 80%+ 折减区的口径与 Montoya 不可直接对比**。Montoya 的约 12% 是**中途充电**中
    补到 80% 以上的比例，那些充电与 10 h 路线时长上限竞争；本项目那 18.37%（36/196）
    是**全部会话**中充到 100% 的比例，而按 `mechanism_condition_absent_20260731.md`，
    恰好就是这 36 个会话产生了时长差、且全部落在行前不竞争时段。
    按 Montoya 的口径（与时间预算竞争的中途充电中进入折减区者），
    **本项目对应的数量为 0**。（FACT + INFERENCE）

**⑩ 运营时域 06:00–22:00（16 h）与路线时长**
- 文献对照：Montoya 最大路线时长 10 h（PDF 第13页）；陈婉茹车辆最大行程时间 8 h（印刷第3330页）；
  Schneider 因绕行充电导致时间窗不可行而重新生成时间窗（印刷第12页）。
- 定位：本项目 16 h 的时域**宽于**这两个对照（10 h、8 h）。
  按 Nafstad 印刷第643页与 Keskin & Çatay PDF 第15页，时间宽松正是文献认定
  "非线性建模收益小"的条件。（FACT + INFERENCE）

**⑪ 服务地理范围**
- 文献对照：Montoya 120×120 km（semi-urban，PDF 第13页）；
  Crevier 车场域 [−50,50]²、客户域 [−100,100]²（印刷第767页）；
  王勇重庆主城区、陈婉茹长-株-潭、Wang×2 重庆核心城区。
- 本项目实测（FACT，从 `cn-prd-50c-01-V2-LOCATIONS/nodes.csv` 的经纬度算得；直线近似，非路网距离）：
  两车场大圆距离 **64.3 km**；全部 54 个节点的经纬度包围盒约 **71 km（南北）× 88 km（东西）**；
  客户按城市分布为深圳 29 / 广州 25。
- 定位：本项目的地理跨度**略小于但同量级于** Montoya 的 120×120 km"semi-urban operation"设定，
  也与 Crevier 生成配方中客户域 [−100,100]²（边长 200 个单位、车场域边长 100 个单位）
  的"客户域宽于车场域"格局同向。（INFERENCE）

---

## 5. 检索方法与可复现脚本

本任务全程只读。三个一次性检索脚本放在 `scripts/`：

| 脚本 | 作用 |
|---|---|
| `zot_lookup.py` | 以只读方式打开 `~/Zotero/zotero.sqlite`，按标题关键词检索条目、把 item key 解析到 storage 里的 PDF 路径、按页导出文本 |
| `pdfgrep.py` | 对单个 PDF 逐页 `pdftotext`，正则命中时打印 **PDF 页号** + 上下文，用于给每条引文定页 |
| `batch_grep.sh` | 对一组 PDF 批量做上一步 |
| `instance_geometry.py` | 从 `nodes.csv` 的经纬度算两车场大圆距离与节点包围盒（§4.2⑪ 用） |

页码偏移量核对结果（用于把 PDF 页号换算成印刷页号）：

| 论文 | 换算 |
|---|---|
| 王勇等 2023 | 印刷 = PDF + 1118 |
| 陈婉茹等 2023 | 印刷 = PDF + 3319 |
| Crevier et al. 2007 | 印刷 = PDF + 755 |
| Dondo & Cerdá 2007 | 印刷 = PDF + 1477 |
| Hiermann et al. 2016 | 印刷 = PDF + 994 |
| Nafstad et al. 2025 | 印刷 = PDF + 626 |
| Schneider et al. 2014 | 印刷 = PDF − 1（Articles in Advance，pp.1–21） |
| 陈雨蝶等 2023 | 印刷 = PDF + 1950（控制与决策 38(7)） |
| 郑荣等 2023 | 印刷 = PDF（偏移量为 0） |
| Montoya 2017 / Froger 2022 / Keskin & Çatay 2016 / Xiao 2021 / Wang 2023 / Wang 2024 / Soriano 2023 / Zhen 2020 / 陈雨蝶 2025 | 预印本、网络首发或以文章号发表，无稳定印刷页码，**一律引 PDF 页号** |

Zotero 库统计：条目 1292 条（非附件/笔记 437 条），PDF 附件 396 个，storage 目录 423 个。
