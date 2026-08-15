# 混合车队与协同成本／收益分配图表摘录

说明：页码均为从 PDF 封面起算的物理页码。表头中的 `—` 只用于展开原表的多层表头，不属于原文。表的“行数”只计数据行，不计表头、脚注和 Average/All/Overall 汇总行；如一行内含多个主体明细，另行注明。图题、表题、表头、图例和正文引句保留英文原文；中文仅放在明确标有“译：”的位置。

## 1. 五个问题的直接答案

### 问题一：甲组 4 篇怎样呈现车队构成

| 条目key | 直接答案 | 编号与 PDF 物理页码 |
|---|---|---|
| JY2IQSFS | 图 | Fig. 6，物理页 13。该图直接给出 EVs 与 ICEVs 的车辆数；Fig. 11（物理页 14）比较 mixed fleet 与 ICEV fleet，但不画各车型车辆数。 |
| LXV64TTK | 表和图 | Table 7、Fig. 7，物理页 21；Fig. 8，物理页 22；Fig. 6，物理页 20。Table 7 列出 `CV`、`EV`，Fig. 7、Fig. 8 的纵轴含 `Number of vehicles`。 |
| FSPIDSY3 | 表和图 | Table 6，物理页 15；Table 7，物理页 16；Tables 8–9，物理页 19–20；Table 10，物理页 22；Table 11 与 Fig. 11，物理页 23；Figs. 8、12、13，物理页 18、24、25。表内列出 `#EV`、`#ICEV` 或两车型里程；路线图用车型路线区分车队构成。 |
| 8526FJ85 | 表和图 | Tables 6–7，物理页 24；Fig. 15，物理页 25。Fig. 15 给出 RSN、RSP、RSG driver proportions；Tables 6–7 给出 RSN 与 RS driver numbers。 |

### 问题二：车队构成随参数变化的图

共 **3 个命中**：

1. LXV64TTK，Fig. 7，物理页 21：横轴 `Unit carbon tax price (CNY/kg)`，纵轴含 `Number of vehicles`，图例含 `EV`、`CV`。
2. LXV64TTK，Fig. 8，物理页 22：横轴 `Penalty cost per unit of time (CNY/min)`，纵轴含 `Number of vehicles`，图例含 `EV`、`CV`。
3. 8526FJ85，Fig. 15，物理页 25：横轴 `Number of public charging piles N_L`，三个纵轴分别是 `Proportion of RSN drivers (%)`、`Proportion of RSP drivers (%)`、`Proportion of RSG drivers (%)`。

JY2IQSFS 与 FSPIDSY3 未找到符合“参数在横轴、车型数量或占比在纵轴”的图。FSPIDSY3 的 Table 11 随 toll values 比较 `#EV` 与 `ICEV in LEZ`，但它是表，不是图。

### 问题三：乙组 11 篇怎样呈现各主体收益／成本分配结果

- 含各主体分配数值表的论文：**7 篇**。
- 含图的论文：**5 篇**。
- 其中图、表都有：**5 篇**；只有表：**2 篇**；只有图：**0 篇**；未呈现各主体分配数值：**4 篇**。

| 条目key | 直接答案 | 编号与 PDF 物理页码 |
|---|---|---|
| 8SZH92A4 | 图和表 | Table 4、Fig. 2，物理页 19；Table 12，物理页 24。 |
| FQM84ZER | 图和表 | Table 12、Fig. 9、Table 13，物理页 18；Table 14、Fig. 10，物理页 19；Table 15，物理页 20；Table 17，物理页 21。 |
| PC6UZBV9 | 图和表 | Figs. 2–3，物理页 10；Table 7，物理页 11。 |
| NPDGC3FF | 图和表 | Tables 7–8，物理页 18；Fig. 5、Tables 9–10，物理页 19；Table 11，物理页 20。 |
| EBX7394P | 未呈现各主体分配数值 | Table 11（物理页 15）只报告 allocation 是否属于 core，没有逐 depot 金额。 |
| MXT65K38 | 未呈现 | 未找到展示各 player 最终 cost allocation 数值的图或表；结果表只报告求解与 core 是否为空。 |
| 5GDKE2YV | 未呈现各主体分配数值 | Table 7（物理页 9）只报告 collaborative per period profit 低于 non-collaborative one 的次数，没有逐 carrier 金额。 |
| JLWN3CXL | 图和表 | Figs. 7–8，物理页 13；Fig. 12，物理页 16；Figs. 13–14，物理页 17；Table 3，物理页 18；Table 5，物理页 19。 |
| QBSC8MCD | 未呈现 | 未找到对各 vehicle 的“单干利润—协同后分配利润”进行图表对照的展品。Figure 2（物理页 22）是故障后的任务重分配路线图，不含利润数值；Tables 2–6 只报告 worst-off/overall profit 与算法结果。 |
| V7V84NMJ | 表 | Tables 4–5，物理页 11–12；Table 6，物理页 12；Table 7，物理页 13；Table 8，物理页 14。 |
| 5LTEZCIB | 表 | Table 4，物理页 29。 |

### 问题四：8SZH92A4 的核心比较表

核心比较表是 **Table 12，PDF 物理页 24**。

表题原文：`Table 12: Indicators obtained under different cost sharing methods.`

译：不同成本分摊方法所得指标。

表头从左到右逐列为：

`原文未标注 | Equally (28) | Proportional to marginal cost (29) | Proportional to distance and load (30) | Shapley value (31) | Our method`

表内比较的方法名逐字为：

- `Equally`
- `Proportional to marginal cost`
- `Proportional to distance and load`
- `Shapley value`
- `Our method`

共 5 个数据行：`Average ΔGini[v] (%)`、`St. dev. ΔGini[v] (%)`、`IR [% instances]`、`OP [% instances]`、`St [% unstable subcoalitions]`。

正文引句：`The results of this comparison, presented in Table 12 show that our method outperforms all the other methods for all indicators.`

### 问题五：“单干”与“协同后分配”两类量的英文原词

| 条目key | PDF 物理页码 | 英文原词或原表头 | 原文句子 |
|---|---:|---|---|
| 8SZH92A4 | 19 | `stand-alone cost`；`cost share in the grand coalition` | `To assess the effects of belonging to the grand coalition, we analyze the savings obtained for the partners as the difference between their stand-alone cost and their cost share in the grand coalition.` |
| FQM84ZER | 18 | `Non-collaborative network`；`Collaborative network` | `Table 11 presents a comparison of costs, the number of vehicles, and waiting time between the non-collaborative network, collaborative network, and reconstructed distribution network.` |
| FQM84ZER | 18 | `Profits ($)`；`Deserved profits ($)` | `Table 13 displays the total profit of each alliance scenario as the collaboration between DCs increases.` |
| PC6UZBV9 | 10 | `own profit`；`collaborative profit` | `Fig. 2 plots the variation of the collaborative profit of each logistics enterprise in Case 1 as the importance degree of the own profit increases.` |
| NPDGC3FF | 17–19 | `independent delivery`；`Profit change` / `Avg. profit change` | `The last column illustrates each member’s profit change compared to independent delivery.` |
| EBX7394P | 14 | `its own travel cost if it operates as an independent service provider`；`allocation of total cost savings` | `A depot needs to consider its own travel cost if it operates as an independent service provider, or if it is owned by a parent company but accounts for its own profit and loss.` / `Taking the game-theoretic perspective, the allocation of total cost savings should belong to the core of the cooperative game in which every depot is a player, and the payoff of any coalition is its total travel cost savings.` |
| MXT65K38 | 7 | `individual cost`；`allocated cost to each player` | `An EPM allocation is a core allocation that minimises the maximum difference in allocated cost to each player, relative to their individual cost.` |
| 5GDKE2YV | 9 | `non-collaborative per period profits`；`collaborative per period profit` | `Comparison of carriers’ per period profits (if they collaborate) compared against non-collaborative per period profits.` |
| JLWN3CXL | 11 | `costs before the auction`；`costs after the auction` | `In Fig. 5(a), the lines show for different rejection parameter settings the carriers’ average collected revenue, costs before the auction (zᵇγ), costs after the auction (zᵃγ), and profit, calculated from the revenue minus the costs after the auction.` |
| JLWN3CXL | 16 | `participating in the exchange`；`not participating` | `Essentially, no carrier should be worse off participating in the exchange than when not participating.` |
| QBSC8MCD | — | 未找到 | 未找到同时指称主体单干利润／成本与协同后分配利润／成本的成对英文原词。 |
| V7V84NMJ | 11–14 | `Non-collaboration`；`Collaboration`；两侧均使用 `Φ (SEK)` | `We use the non-collaboration scenarios as the baselines, where each company’s costs and profits are calculated separately.` |
| 5LTEZCIB | 29 | `Initial`；`Cooperative planning`；两侧均使用 `UC`、`ΣQ` | `It is observed that the unit cost (UC) and collected load (ΣQ) after the cooperative planning of provider 1 (blue) remain approximately the same as before.` |

## 2. 甲组逐篇图表清单

### 2.1 JY2IQSFS｜Shi 等 2025

#### Fig. 6

- PDF 物理页码：13
- 类型：图
- 图题原文：`Fig. 6. Number of EVs and ICEVs in the most profitable scenarios.`
- 译：最有利可图情景中的 EV 与 ICEV 数量。
- 横轴：两个子图均为 `case 1`、`case 2`、`case 3`；原文未标注横轴名称和单位。
- 纵轴：左子图左轴 `Profit`、右轴 `Number of vehicles`；右子图左轴 `Carbon Emissions`、右轴 `Number of vehicles`；原文未标注单位。
- 子图：2 个，横向 1×2 排布。
- 图例：左子图 `ICEV`、`EV`、`Profit`；右子图 `ICEV`、`EV`、`Carbon Emissions`。
- 正文引句：`Fig. 6 depicts the composition of EVs and ICEVs used in the most profitable scenarios for each set of instances.`

#### Fig. 11

- PDF 物理页码：14
- 类型：图
- 图题原文：`Fig. 11. Comparison between the mixed fleet and the fleet composed of ICEVs.`
- 译：混合车队与 ICEV 车队的比较。
- 横轴：`case 1` 至 `case 6`；原文未标注横轴名称和单位。
- 纵轴：左轴 `Profit`；右轴 `Carbon Emissions`；原文未标注单位。
- 子图：1 个。
- 图例：`ICEV-profit`、`MF-profit`、`MF-CO2`、`ICEV-CO2`。
- 正文引句：`Fig. 11 presents a comparison between using a mixed fleet and a fleet composed of ICEVs.`

### 2.2 LXV64TTK｜Ma 等 2024

#### Figure 6

- PDF 物理页码：20
- 类型：图
- 图题原文：`Figure 6. Delivery routes under four scenarios. (a) Scenario 1 (b) Scenario 2 (c) Scenario 3 (d) Scenario 4`
- 译：四种情景下的配送路线。（a）情景 1；（b）情景 2；（c）情景 3；（d）情景 4。
- 横轴、纵轴：均为无名称的数值坐标轴；原文未标注单位。
- 子图：4 个，2×2 排布。
- 图例：（a）`CV 1`、`CV 2`、`CV 3`、`CV 4`、`CV 5`、`CV 6`、`CV 7`、`Store`、`BSS`、`Depot`；（b）`CV 1`、`CV 2`、`CV 3`、`CV 4`、`CV 5`、`CV 6`、`EV 1`、`EV 2`、`Store`、`BSS`、`Depot`；（c）`CV 1`、`CV 2`、`CV 3`、`CV 4`、`EV 1`、`EV 2`、`EV 3`、`EV 4`、`EV 5`、`Store`、`BSS`、`Depot`；（d）`CV 1`、`CV 2`、`CV 3`、`CV 4`、`EV 1`、`EV 2`、`EV 3`、`EV 4`、`EV 5`、`EV 6`、`Store`、`BSS`、`Depot`。
- 正文引句：`Figure 6 depicts the derived delivery routes under each scenario.`

#### Table 7

- PDF 物理页码：21
- 类型：表
- 表题原文：`Table 7. Costs under four delivery scenarios.`
- 译：四种配送情景下的成本。
- 表头从左到右：`No. | Scenario—Accessible time windows | Scenario—Bearing weight | CV | EV | TOC | SC | DC | EC | CTC | PC`
- 数据行：4 行。
- 正文引句：`The detailed results for the four scenarios are provided in Table 7, including the number of vehicles used, the total operations costs, and the specific cost compositions.`

#### Figure 7

- PDF 物理页码：21
- 类型：图
- 图题原文：`Figure 7. Impact of the unit carbon tax price on carbon emissions and the number of vehicles used.`
- 译：单位碳税价格对碳排放与车辆使用数量的影响。
- 横轴：`Unit carbon tax price (CNY/kg)`。
- 纵轴：左轴 `Carbon emissions (kg)`；右轴 `Number of vehicles`。
- 子图：1 个。
- 图例：`Carbon emissions`、`EV`、`CV`。
- 正文引句：`Figure 7 shows the variations in the amount of carbon emissions and the numbers of CVs and EVs used when the unit carbon tax price increases from 0.06 CNY/kg to 0.14 CNY/kg.`

#### Figure 8

- PDF 物理页码：22
- 类型：图
- 图题原文：`Figure 8. Effects of the penalty cost per unit of time on the waiting time and numbers of vehicles used.`
- 译：单位时间惩罚成本对等待时间与车辆使用数量的影响。
- 横轴：`Penalty cost per unit of time (CNY/min)`。
- 纵轴：左轴 `Time (min)`；右轴 `Number of vehicles`。
- 子图：1 个。
- 图例：`Wait time`、`EV`、`CV`。
- 正文引句：`As shown in Figure 8, when the penalty cost per unit of time increases from 0.3 to 1.0, the number of CVs used decreases from 4 to 2, and the number of EVs used increases from 6 to 8.`

### 2.3 FSPIDSY3｜Bruglieri 等 2025

#### Table 6

- PDF 物理页码：15
- 类型：表
- 表题原文：`Table 6 Comparison with the solutions of Amiri et al. (2023a).`
- 译：与 Amiri 等（2023a）解的比较。
- 表头从左到右：`Instance—Size | Instance—#Inst | Amiri et al. (2023a)—TC | Amiri et al. (2023a)—#EV | Amiri et al. (2023a)—#ICEV | Amiri et al. (2023a)—t(s) | This Study—Same fleet mix—TC—Δ(%) | This Study—Same fleet mix—TC—#Better | This Study—Same fleet mix—t(s) | This Study—Reduced fleet—TC—Δ(%) | This Study—Reduced fleet—TC—#Better | This Study—Reduced fleet—#ICEV—Δ(%) | This Study—Reduced fleet—#ICEV—#Better | This Study—Reduced fleet—t(s)`
- 数据行：2 行。
- 正文引句：`In Table 6, columns 3–5 present the average total cost (“TC”), average number of EVs (“#EV”), and average number of ICEVs (“#ICEV”) obtained by Amiri et al. (2023a).`

#### Table 7

- PDF 物理页码：16
- 类型：表
- 表题原文：`Table 7 Summary of results for small-size instances.`
- 译：小规模算例结果汇总。
- 表头从左到右：`Instances | #EV | Mathematical model—TC | Mathematical model—t(s) | Mathematical model—% Gap | ALNS—TC | ALNS—t(s) | Solution characteristics—TD_EV | Solution characteristics—TD_ICEV | Solution characteristics—#ICEV in LEZ | Solution characteristics—#RS`
- 数据行：42 行。
- 正文引句：`The results for small-size instances with 15 customers are presented in Table 7.`

#### Fig. 8

- PDF 物理页码：18
- 类型：图
- 图题原文：`Fig. 8. Illustration of ICEV-only and mixed-fleet solutions for RC103 instance.`
- 译：RC103 算例的纯 ICEV 解与混合车队解示意。
- 横轴、纵轴：路线图；原文未标注坐标轴名称和单位。
- 子图：2 个，纵向 2×1 排布；`a. ICEV-only solution (TC: 2189.77)`、`b. Mixed-fleet solution (TC: 1947.40)`。
- 图例：原文未设置独立图例。
- 正文引句：`Fig. 8-b shows the solution of the same problem when a mixed fleet is used.`

#### Tables 8–10

- 类型：表。
- Table 8：PDF 物理页 19；表题原文 `Table 8 Summary of results for C-type instances.`；译：C 型算例结果汇总；数据行 33 行。
- Table 9：PDF 物理页 20；表题原文 `Table 9 Summary of results for R-type instances.`；译：R 型算例结果汇总；数据行 39 行。
- Table 10：PDF 物理页 22；表题原文 `Table 10 Summary of results for RC-type instances.`；译：RC 型算例结果汇总；数据行 33 行。
- Table 8 表头从左到右：`#Cust in LEZ | #EV | C103 (Fleet size = 10)—TD_EV | C103 (Fleet size = 10)—TD_ICEV | C103 (Fleet size = 10)—#ICEV in LEZ | C103 (Fleet size = 10)—TC | C103 (Fleet size = 10)—ΔTC(%) | C103 (Fleet size = 10)—t(s) | C103 (Fleet size = 10)—#RS | C106 (Fleet size = 10)—TD_ICEV | C106 (Fleet size = 10)—TD_EV | C106 (Fleet size = 10)—#ICEV in LEZ | C106 (Fleet size = 10)—TC | C106 (Fleet size = 10)—ΔTC(%) | C106 (Fleet size = 10)—t(s) | C106 (Fleet size = 10)—#RS`。
- Table 9 表头从左到右：`#Cust in LEZ | #EV | R102 (Fleet size = 15)—TD_EV | R102 (Fleet size = 15)—TD_ICEV | R102 (Fleet size = 15)—#ICEV in LEZ | R102 (Fleet size = 15)—TC | R102 (Fleet size = 15)—ΔTC(%) | R102 (Fleet size = 15)—t(s) | R102 (Fleet size = 15)—#RS | R107 (Fleet size = 10)—TD_EV | R107 (Fleet size = 10)—TD_ICEV | R107 (Fleet size = 10)—#ICEV in LEZ | R107 (Fleet size = 10)—TC | R107 (Fleet size = 10)—ΔTC(%) | R107 (Fleet size = 10)—t(s) | R107 (Fleet size = 10)—#RS`。
- Table 10 表头从左到右：`#Cust in LEZ | #EV | RC103 (Fleet size = 12)—TD_EV | RC103 (Fleet size = 12)—TD_ICEV | RC103 (Fleet size = 12)—#ICEV in LEZ | RC103 (Fleet size = 12)—TC | RC103 (Fleet size = 12)—ΔTC(%) | RC103 (Fleet size = 12)—t(s) | RC103 (Fleet size = 12)—#RS | RC108 (Fleet size = 10)—TD_ICEV | RC108 (Fleet size = 10)—TD_EV | RC108 (Fleet size = 10)—#ICEV in LEZ | RC108 (Fleet size = 10)—TC | RC108 (Fleet size = 10)—ΔTC(%) | RC108 (Fleet size = 10)—t(s) | RC108 (Fleet size = 10)—#RS`。
- 正文引句：`We perform 30 runs for each instance and report the best results in Tables 8–10, in which the first two columns show the number of customers in the LEZ in each instance and the number of EVs in the fleet, respectively.`

#### Table 11

- PDF 物理页码：23
- 类型：表
- 表题原文：`Table 11 Sensitivity of results to different toll values.`
- 译：结果对不同通行费数值的敏感性。
- 表头从左到右：`#Cust in LEZ | Instances | #EV | No toll—ΔTC(%) | No toll—ICEV in LEZ—# | 2 × Toll—ΔTC(%) | 2 × Toll—ICEV in LEZ—# | 2 × Toll—ICEV in LEZ—Δ | 10 × Toll—ΔTC(%) | 10 × Toll—ICEV in LEZ—# | 10 × Toll—ICEV in LEZ—Δ`
- 数据行：28 行。
- 正文引句：`Table 11 presents these comparisons, where the third column shows the number of EVs in the fleet, ΔTC(%) shows the percentage change in the total cost, and # and Δ denote the number of ICEVs entering the LEZ and the change in this number with respect to the base case, respectively.`

#### Fig. 11

- PDF 物理页码：23
- 类型：图
- 图题原文：`Fig. 11. Delivery routes in base-case scenario.`
- 译：基准情景中的配送路线。
- 横轴、纵轴：地图；原文未标注坐标轴；比例尺 `2 km`。
- 子图：2 个，横向 1×2 排布；`a. ICEV fleet`、`b. EV fleet`。
- 图例：左图 `ICEV Route 1`、`ICEV Route 2`、`Total cost = €14.96`；右图 `EV Route 1`、`EV Route 2`、`Total cost = €3.09`。
- 正文引句：`When the fleet consists of two EVs, we observe that both enter Area C free of charge, resulting in a much improved route plan with a total cost of €3.09 (see Fig. 11.b).`

#### Fig. 12

- PDF 物理页码：24
- 类型：图
- 图题原文：`Fig. 12. Delivery routes for two different vehicle load capacities.`
- 译：两种不同车辆载重能力下的配送路线。
- 横轴、纵轴：地图；原文未标注坐标轴；比例尺 `2 km`。
- 子图：2 个，横向 1×2 排布；`a. 150 kg-capacity vehicle`、`b. 450 kg-capacity vehicle`。
- 图例：左图 `EV Route`、`ICEV Route 1`、`ICEV Route 2`、`Total cost = €13.04`；右图 `EV Route`、`ICEV Route`、`Total cost = €5.48`。
- 正文引句：`Since the total demand of the customers living in Area C exceeds 150 kg, one ICEV has to enter Area C and pay the €7.50 toll, resulting in a total cost of €13.04 (see Fig. 12.a).`

#### Fig. 13

- PDF 物理页码：25
- 类型：图
- 图题原文：`Fig. 13. Delivery routes for two different customer time-window options.`
- 译：两种不同客户时间窗选项下的配送路线。
- 横轴、纵轴：地图；原文未标注坐标轴；比例尺 `2 km`。
- 子图：2 个，横向 1×2 排布；`a. 1-hour time windows`、`b. No time windows`。
- 图例：左图 `EV Route`、`ICEV Route 1`、`ICEV Route 2`、`Total cost = €6.05`；右图 `EV Route`、`ICEV Route`、`Total cost = €3.89`。
- 正文引句：`Different from that scenario, the EV serves all the customers inside Area C, so ICEVs do not pay any toll (see Fig. 13.a).`

### 2.4 8526FJ85｜Cai 等 2023

#### Table 6

- PDF 物理页码：24
- 类型：表
- 表题原文：`Table 6 Comparison of market states without and with integrated services in the PM regime.`
- 译：PM 制度下无整合服务与有整合服务的市场状态比较。
- 上半表表头从左到右：`Number of public charging piles N_L | Π_max without integrated service | Π_max with integrated service | Improvement of Π_max | Charging profit Π_c | Proportion of Π_c`
- 下半表表头从左到右：`Number of public charging piles N_L | Access time—T̂_L | Access time—T_L | Number of RSN drivers—Q̂_rs^n | Number of RSN drivers—Q_rs^n | Number of RS drivers—Q̂_rs | Number of RS drivers—Q_rs`
- 数据行：上下半表各 8 行，对应相同 8 个 `N_L` 值。
- 正文引句：`Table 6 demonstrates the change in maximum profit, access time, number of RSN drivers, and RS drivers in the PM regime, where the results under different N_L are presented.`

#### Table 7

- PDF 物理页码：24
- 类型：表
- 表题原文：`Table 7 Comparison of market states without and with integrated services in the SO regime.`
- 译：SO 制度下无整合服务与有整合服务的市场状态比较。
- 上半表表头从左到右：`Number of public charging piles N_L | SW_max without integrated service | SW_max with integrated service | Improvement in SW_max | Charging profit Π_c | Π with integrated service`
- 下半表表头从左到右：`Number of public charging piles N_L | Access time—T̂_L | Access time—T_L | Number of RSN drivers—Q̂_rs^n | Number of RSN drivers—Q_rs^n | Number of RS drivers—Q̂_rs | Number of RS drivers—Q_rs`
- 数据行：上下半表各 8 行，对应相同 8 个 `N_L` 值。
- 正文引句：`The differences in maximum social welfare, access time, number of RSN drivers, and RS drivers between the two markets (i.e., without and with integrated services) in the SO regime are presented in Table 7.`

#### Fig. 15

- PDF 物理页码：25
- 类型：图
- 图题原文：`Fig. 15. Impact of the integrated services on RS driver composition.`
- 译：整合服务对 RS driver composition 的影响。
- 横轴：三个子图均为 `Number of public charging piles N_L`；原文未标注单位。
- 纵轴：（a）`Proportion of RSN drivers (%)`；（b）`Proportion of RSP drivers (%)`；（c）`Proportion of RSG drivers (%)`。
- 子图：3 个，上方 2 个、下方居中 1 个。
- 图例：三个子图均为 `Without integrated service`、`With integrated service`。
- 正文引句：`Fig. 15 shows the impact of the integrated services on RSN, RSP, and RSG driver proposition in the PM regime.`

## 3. 乙组逐篇图表清单

### 3.1 8SZH92A4｜Rodríguez-Pereira 等 2026

#### Table 4

- PDF 物理页码：19
- 类型：表
- 表题原文：`Table 4: Average savings in percentage of the stand-alone cost v_p/ζ(p) of belonging to the grand coalition.`
- 译：加入 grand coalition 后，相对于 stand-alone cost v_p/ζ(p) 的平均百分比节省。
- 表头从左到右：`Instance | Average over 40 versions of the model—Min | Average over 40 versions of the model—Max | Average over 40 versions of the model—Average | Average over 40 versions of the model—St. Dev.`
- 数据行：13 行。
- 正文引句：`Table 4 provides this statistic for each instance over 40 versions of the model based on different objectives-properties combinations.`

#### Figure 2

- PDF 物理页码：19
- 类型：图
- 图题原文：`Figure 2: CAPÉ partners savings percentage among all model variants.`
- 译：所有模型变体下 CAPÉ partners 的节省百分比。
- 横轴：`CAPÉ partners`，类别 `p1` 至 `p13`。
- 纵轴：`Saving percentage`；原文未标注单位符号。
- 子图：1 个箱线图。
- 图例：原文未标注。
- 正文引句：`More precisely, in the CAPÉ instance, the negative savings occur for partners 1, 4, 5, 10, 11, 12, and 13 (see Figure 2).`

#### Table 12

- PDF 物理页码：24
- 类型：表
- 表题原文：`Table 12: Indicators obtained under different cost sharing methods.`
- 译：不同成本分摊方法所得指标。
- 表头从左到右：`原文未标注 | Equally (28) | Proportional to marginal cost (29) | Proportional to distance and load (30) | Shapley value (31) | Our method`
- 数据行：5 行。
- 正文引句：`The results of this comparison, presented in Table 12 show that our method outperforms all the other methods for all indicators.`

### 3.2 FQM84ZER｜Wang 等 2023

#### Table 12

- PDF 物理页码：18
- 类型：表
- 表题原文：`Table 12 Deserved profit allocation results with different models.`
- 译：不同模型下的 deserved profit allocation 结果。
- 表头从左到右：`DCs | Core center | Profit allocation models—Improved MCRS | Profit allocation models—Shapley | Profit allocation models—GQP | Profit allocation models—EPM`
- 数据行：5 行，其中 4 行为 DC，1 行为 `Distance`。
- 正文引句：`The results of the deserved profit allocation schemes generated by these models are presented in Table 12.`

#### Fig. 9

- PDF 物理页码：18
- 类型：图
- 图题原文：`Fig. 9. Comparative results of the different deserved profit allocation schemes.`
- 译：不同 deserved profit allocation schemes 的比较结果。
- 横轴、纵轴：示意图；原文未标注坐标轴和单位。
- 子图：1 个。
- 图内文字：`EPM`、`Shapley`、`Core`、`GQP`、`MCRS`；原文未设置独立图例。
- 正文引句：`Fig. 9 illustrates the distances between the profit allocation schemes generated by different models and the core center.`

#### Table 13

- PDF 物理页码：18
- 类型：表
- 表题原文：`Table 13 Alliance profit and deserved profit of each member in the collaborative distribution network.`
- 译：协同配送网络中各联盟的利润与各成员的 deserved profit。
- 表头从左到右：`Alliances | Profits ($) | Deserved profits ($) | Alliances | Profits ($) | Deserved profits ($)`
- 数据行：15 个 alliance 记录，以左右两个区块并排排版。
- 正文引句：`Table 13 displays the total profit of each alliance scenario as the collaboration between DCs increases.`

#### Table 14

- PDF 物理页码：19
- 类型：表
- 表题原文：`Table 14 Profits, losses, and compensations of the various alliances under different default situations.`
- 译：不同违约情形下各联盟的利润、损失与补偿。
- 表头从左到右：`Defaulting DCs | Current alliance A | Profits of A before default | Profits of A after default | Losses of A | R1 | Compensation`
- 数据行：14 行。
- 正文引句：`The results are presented in Table 14.`

#### Fig. 10

- PDF 物理页码：19
- 类型：图
- 图题原文：`Fig. 10. Comparison of the profits and losses of the current alliances under different default situations.`
- 译：不同违约情形下当前联盟利润与损失的比较。
- 横轴：`Current alliances`。
- 纵轴：左轴 `Profits and losses ($)`；右轴 `Ratio`。
- 子图：1 个。
- 图例：`Profits of current alliances before default`、`Losses of current alliances after default`、`R₁`；图内分组文字 `One defaulting DC`、`Two defaulting DCs`、`Three defaulting DCs`。
- 正文引句：`Fig. 10 provides a comparison of the profits and losses of the current alliance in different default situations.`

#### Table 15

- PDF 物理页码：20
- 类型：表
- 表题原文：`Table 15 Default costs and compensation in different default situations.`
- 译：不同违约情形下的违约成本与补偿。
- 表头从左到右：`Defaulting DCs | Default costs | Total default costs | Non-defaulting DCs | Compensation | Total compensation`
- 数据行：14 行。
- 正文引句：`Furthermore, Table 15 provides the allocated default cost for each defaulting DC.`

#### Table 17

- PDF 物理页码：21
- 类型：表
- 表题原文：`Table 17 Vehicle routes of non-defaulting DC2 in four cases.`
- 译：四种情形下未违约 DC2 的车辆路线。
- 表头从左到右：`Cases | Vehicle routes | Delivery cost ($) | Wait time (min) | Number of vehicles | Compensation ($)`
- 数据行：4 行。
- 正文引句：`Furthermore, the vehicle routes for non-defaulting DC2 across for four cases are displayed in Table 17, and the vehicle routes for Cases c and d are depicted in Fig. 12 to allow for the analysis of how non-defaulting members’ vehicle routes change as the number of defaulting DCs increases.`

### 3.3 PC6UZBV9｜Liu 等 2021

#### Fig. 2

- PDF 物理页码：10
- 类型：图
- 图题原文：`Fig. 2. Profit variation partially fails to satisfy the individual rationality.`
- 译：利润变化部分未满足 individual rationality。
- 横轴：`w_p`；原文未标注单位。
- 纵轴：`x^{ωw*}(i)`；原文未标注单位。
- 子图：1 个。
- 图例：`Logistics enterprise 1`、`Logistics enterprise 2`、`Logistics enterprise 3`、`Logistics enterprise 4`、`Boundary`；图内区域文字 `Not satisfying the individual rationality`、`satisfying the individual rationality`。
- 正文引句：`Fig. 2 plots the variation of the collaborative profit of each logistics enterprise in Case 1 as the importance degree of the own profit increases.`

#### Fig. 3

- PDF 物理页码：10
- 类型：图
- 图题原文：`Fig. 3. Profit variation fully satisfies the individual rationality.`
- 译：利润变化完全满足 individual rationality。
- 横轴：`w_p`；原文未标注单位。
- 纵轴：`x^{ωw*}(i)`；原文未标注单位。
- 子图：1 个。
- 图例：`Logistics enterprise 1`、`Logistics enterprise 2`、`Logistics enterprise 3`、`Logistics enterprise 4`、`Boundary`。
- 正文引句：`Using the Lingo software, Algorithm 1 ultimately yields the improved profit allocation schemes as shown in Fig. 3.`

#### Table 7

- PDF 物理页码：11
- 类型：表
- 表题原文：`Table 7 Different profit allocation schemes.`
- 译：不同利润分配方案。
- 表头从左到右：`Enterprise | Principle—Own profit only | Principle—Contribution only | ω(1)=0.10, ω(2)=0.40, ω(3)=0.32, ω(4)=0.18—w_p=0.5, w_c=0.5 | ω(1)=0.10, ω(2)=0.40, ω(3)=0.32, ω(4)=0.18—w_p=0.3, w_c=0.7`
- 数据行：4 行。
- 正文引句：`Considering simultaneously the weights and the importance degrees of both the own profit and contribution, corresponding profit allocation schemes in various variables are obtained as shown in Table 7.`

### 3.4 NPDGC3FF｜Liu 等 2025

#### Table 7

- PDF 物理页码：18
- 类型：表
- 表题原文：`Table 7 Comparison of the coalition structure and corresponding revenue: full vs. incomplete information-sharing.`
- 译：完整与不完整信息共享下的 coalition structure 及相应 revenue 比较。
- 表头从左到右：`Info. sharing | Coalition structure | Coal. costs | Member revenue | Member costs | Profit change`
- 数据行：2 个信息共享场景块，每块含 4 个 member 明细，共 8 个主体明细行。
- 正文引句：`Table 7 presents the coalition structures and corresponding allocation results.`

#### Table 8

- PDF 物理页码：18
- 类型：表
- 表题原文：`Table 8 Experimental results and associated computing time under four heterogeneous information-sharing scenarios.`
- 译：四种异质信息共享情景下的实验结果与相应计算时间。
- 表头从左到右：`l₁, l₂, l₃, l₄ | Coalition structure | Profit structure | Total computing time`
- 数据行：4 个场景块，每块含 4 个 carrier 的 `Δs` 明细。
- 正文引句：`We present the coalition structures, carriers’ profit changes and associated computing time for the four scenarios in Table 8, with detailed results provided in Table A.2 to A.4 in Appendix A.`

#### Fig. 5

- PDF 物理页码：19
- 类型：图
- 图题原文：`Fig. 5. The average profit growth and average profit rate for each information disclosure preference under four heterogeneous information-sharing scenarios.`
- 译：四种异质信息共享情景下各信息披露偏好的平均利润增长与平均利润率。
- 横轴：`Information disclosure preference`，类别 `L₁`、`L₂`、`L₃`、`L₄`。
- 纵轴：左轴 `Average profit growth (unit: CNY)`；右轴 `Average profit rate %`。
- 子图：1 个。
- 图例：原文未设置独立图例；柱内标利润增长数值，折线点上标利润率百分数。
- 正文引句：`To further evaluate the value of shared information for coalitions and carriers, Fig. 5 presents the average profit growths compared to independent delivery (in bars) and carriers’ average profit rates (in lines) for each information disclosure preference of the four heterogeneous information-sharing scenarios.`

#### Table 9

- PDF 物理页码：19
- 类型：表
- 表题原文：`Table 9 Average performance of target carriers in a low-information-sharing environment.`
- 译：低信息共享环境中目标 carriers 的平均表现。
- 表头从左到右：`Disclosure level | Avg.order allocation share | Avg.delivery distance | Avg.operational cost per order | Avg.profit change`
- 数据行：4 行。
- 正文引句：`Table 9 and Table 10 summarize the results in the two environments.`

#### Table 10

- PDF 物理页码：19
- 类型：表
- 表题原文：`Table 10 Average performance of target carriers in a high-information-sharing environment.`
- 译：高信息共享环境中目标 carriers 的平均表现。
- 表头从左到右：`Disclosure level | Avg.order allocation share | Avg.delivery distance | Avg.operational cost per order | Avg.profit change`
- 数据行：4 行。
- 正文引句：`Table 9 and Table 10 summarize the results in the two environments.`

#### Table 11

- PDF 物理页码：20
- 类型：表
- 表题原文：`Table 11 Coalition structures and carriers’ profit changes based on the equal contribution division value.`
- 译：基于 equal contribution division value 的 coalition structures 与 carriers’ profit changes。
- 表头从左到右：`l₁, l₂, l₃, l₄ | Coalition structure | Profit change`
- 数据行：4 个场景块，每块含 4 个 carrier 的 `Δs` 明细。
- 正文引句：`The coalition structures and the allocation results are presented in Table 11 with detailed allocation results provided in Table A.13 to Table A.16 in Appendix A.`

### 3.5 EBX7394P｜Zhang 等 2022

#### Table 11

- PDF 物理页码：15
- 类型：表
- 表题原文：`Table 11 The number of instances whose allocation belong to the core.`
- 译：allocation 属于 core 的算例数量。
- 表头从左到右：`Allocation mechanism | #InCore`
- 数据行：3 行，分别为 `No allocation`、`Equal division`、`Shapley value allocation`。
- 正文引句：`The result is summarized in Table 11.`

### 3.6 MXT65K38｜van Zon 等 2021

未找到展示各 player 最终 cost allocation 数值的图或表。文中定义了 `cost allocated to player i as y_i`、`core allocation` 和 `EPM allocation`，但 Tables 1–5 报告的是 solution methods、core 是否为空与计算时间；Figure 1 是 fractional routing solution 示例。

### 3.7 5GDKE2YV｜Mancini 等 2021

#### Table 7

- PDF 物理页码：9
- 类型：表
- 表题原文：`Table 7 Comparison of carriers’ per period profits (if they collaborate) compared against non-collaborative per period profits. We report the number of times the collaborative per period profit is lower than the non-collaborative one. The right-most two columns report the number of days in which a carrier does not perform any service in the non-collaborative and in the collaborative scenarios, respectively.`
- 译：比较 carriers 协同时的逐期利润与非协同逐期利润；报告协同逐期利润更低的次数，以及两种情景下 carrier 不执行服务的天数。
- 表头从左到右：`Instance | Daily profit violations | No service days non-collaborative | No service days collaborative`
- 数据行：20 行。
- 正文引句：`In Table 7 we report the number of times, a carrier has a lower per period profit, if the carrier enters the collaboration, compared against the non-collaborative solution.`

### 3.8 JLWN3CXL｜Scherr 等 2026

#### Fig. 7

- PDF 物理页码：13
- 类型：图
- 图题原文：`Fig. 7. Impact on profit of deviating and not-deviating carriers in heterogeneous rejection settings compared to best homogeneous rejection setting (α = 2.00) for D10 instances with fixed revenue. Profit sharing using the adjustable mechanism with ρ = {0, 1/3, 2/3, 1} and the Shapley Value (SV). Boxplot bars depict the minimum, first quartile, median, third quartile, maximum, and mean (diamond) value.`
- 译：固定 revenue 的 D10 算例中，异质拒绝设置下偏离与不偏离 carriers 相对最佳同质拒绝设置的利润影响。
- 横轴：两个子图均为 `Profit-sharing mechanism`，刻度 `ρ = 0`、`ρ = 1/3`、`ρ = 2/3`、`ρ = 1`、`SV`。
- 纵轴：两个子图均为 `Impact on profit`；原文未标注单位。
- 子图：2 个，横向 1×2 排布；`(a) One carrier rejects less (α − 0.25).`、`(b) One carrier rejects more (α + 0.25).`
- 图例：两个子图均为 `Not deviating`、`Deviating`。
- 正文引句：`Fig. 7 contains the results with fixed revenue, with Fig. 7(a) showing a deviation of rejecting less and Fig. 7(b) a deviation of rejecting more.`

#### Fig. 8

- PDF 物理页码：13
- 类型：图
- 图题原文：`Fig. 8. Impact on profit of deviating and not-deviating carriers in heterogeneous rejection settings compared to best homogeneous rejection setting (α = 2.00) for D10 instances with variable revenue. Profit sharing using the adjustable mechanism with ρ = {0, 1/3, 2/3, 1} and the Shapley Value (SV).`
- 译：可变 revenue 的 D10 算例中，异质拒绝设置下偏离与不偏离 carriers 相对最佳同质拒绝设置的利润影响。
- 横轴：两个子图均为 `Profit-sharing mechanism`，刻度 `ρ = 0`、`ρ = 1/3`、`ρ = 2/3`、`ρ = 1`、`SV`。
- 纵轴：两个子图均为 `Impact on profit`；原文未标注单位。
- 子图：2 个，横向 1×2 排布；`(a) One carrier rejects less (α − 0.25).`、`(b) One carrier rejects more (α + 0.25).`
- 图例：两个子图均为 `Not deviating`、`Deviating`。
- 正文引句：`The results for variable revenue are similarly depicted in Fig. 8, showing the deviation to less rejection in Fig. 8(a) and to more rejection in Fig. 8(b).`

#### Fig. 12

- PDF 物理页码：16
- 类型：图
- 图题原文：`Fig. 12. Impact on profit of different overbooking settings for D10 instances. Profit sharing using the adjustable profit-sharing mechanism with ρ = {0, 1/3, 2/3, 1} and the Shapley Value (SV). Boxplot bars depict the minimum, first quartile, median, third quartile, maximum, and mean (diamond) value for the profit difference of a carrier group compared to the homogeneous setting without overbooking.`
- 译：D10 算例中不同 overbooking 设置对利润的影响。
- 横轴：两个子图均为 `Profit-sharing mechanism`，刻度 `ρ = 0`、`ρ = 1/3`、`ρ = 2/3`、`ρ = 1`、`SV`。
- 纵轴：两个子图均为 `Impact on profit`；原文未标注单位。
- 子图：2 个，横向 1×2 排布；`(a) Fixed revenue.`、`(b) Variable revenue.`
- 图例：`1/3 No OB`、`2/3 OB`、`3/3 OB`。
- 正文引句：`Analogously, the results with variable revenue and fixed outsourcing costs are shown in Fig. 12(b).`

#### Fig. 13

- PDF 物理页码：17
- 类型：图
- 图题原文：`Fig. 13. Impact on profit for different deviating carriers in the D10-20 instances. Profit sharing using the adjustable profit-sharing mechanism with ρ = {0, 1/3, 2/3, 1} and the Shapley Value (SV).`
- 译：D10-20 算例中不同偏离 carriers 的利润影响。
- 横轴：两个子图均为 `Profit-sharing mechanism`，刻度 `ρ = 0`、`ρ = 1/3`、`ρ = 2/3`、`ρ = 1`、`SV`。
- 纵轴：两个子图均为 `Impact on profit`；原文未标注单位。
- 子图：2 个，横向 1×2 排布；`(a) Fixed revenue.`、`(b) Variable revenue.`
- 图例：`Close carrier No OB`、`Remote carrier No OB`、`3/3 OB`。
- 正文引句：`Fig. 13 analyzes the impact of overbooking for the D10-20 instances with mixed distances between the three carriers’ depots.`

#### Fig. 14

- PDF 物理页码：17
- 类型：图
- 图题原文：`Fig. 14. Collaboration savings of each carrier with different profit-sharing mechanisms (D10 instances with fixed revenue and outsourcing costs).`
- 译：不同 profit-sharing mechanisms 下每个 carrier 的 collaboration savings。
- 横轴：5 个子图均为 `Carrier #`，类别 `1`、`2`、`3`。
- 纵轴：5 个子图均为 `Collaboration savings`；原文未标注单位。
- 子图：5 个，前两行各 2 个、末行居中 1 个；`(a) Adjustable profit-sharing mechanism with ρ = 0.`、`(b) Adjustable profit-sharing mechanism with ρ = 1/3.`、`(c) Adjustable profit-sharing mechanism with ρ = 2/3.`、`(d) Adjustable profit-sharing mechanism with ρ = 1.`、`(e) Shapley Value profit sharing.`
- 图例：原文未设置独立图例。
- 正文引句：`Fig. 14 shows for each evaluated profit-sharing mechanism the absolute collaboration savings obtained for each carrier and each instance.`

#### Table 3

- PDF 物理页码：18
- 类型：表
- 表题原文：`Table 3 Minimum parameter value of ρ providing positive collaboration savings for all carriers in different instances.`
- 译：在不同算例中使所有 carriers 获得正 collaboration savings 的最小 ρ 值。
- 表头从左到右：`Revenue | Fixed | Variable`；第二层为 `Outsourcing costs | Fixed | Variable | Fixed | Variable`。
- 数据行：2 行，`D10 instances`、`D20 instances`。
- 正文引句：`In Table 3, we report the minimum ρ value for which this is the case in different settings, namely per revenue and outsourcing cost pattern for D10 and D20 instances.`

#### Table 5

- PDF 物理页码：19
- 类型：表
- 表题原文：`Table 5 Impact of deviating strategies on carrier profit in the D10 instances with different revenue patterns. Profit sharing using the adjustable profit-sharing mechanism with ρ = {0, 1/3, 2/3, 1} and the Shapley Value (SV).`
- 译：不同 revenue patterns 下偏离策略对 D10 算例 carrier profit 的影响。
- 表头从左到右：`Deviating strategy | Fixed revenue—ρ = 0 | Fixed revenue—ρ = 1/3 | Fixed revenue—ρ = 2/3 | Fixed revenue—ρ = 1 | Fixed revenue—SV | Variable revenue—ρ = 0 | Variable revenue—ρ = 1/3 | Variable revenue—ρ = 2/3 | Variable revenue—ρ = 1 | Variable revenue—SV`
- 数据行：3 行，`Rejecting less`、`Rejecting more`、`No overbooking`。
- 正文引句：`Table 5 summarizes how a carrier’s profit is impacted by deviating from the best homogeneous strategy given different settings of the profit-sharing mechanism.`

### 3.9 QBSC8MCD｜Sánchez 等 2024

未找到符合本次口径的图或表。Figure 2（物理页 22，题为 `Figure 2: Example of the execution of the dynamic approach when vehicle 1 breaks down in the middle of its route.`）画的是任务与路线重分配，图内没有各 vehicle 利润数值；利润数字只出现在物理页 21 的正文项目符号中。Tables 2–6 仅给 `Worst`、`Overall` 等聚合结果或算法比较，没有各 vehicle 的“单独时—协同后”分配对照。

### 3.10 V7V84NMJ｜Zhou 等 2024

#### Table 4

- PDF 物理页码：11
- 类型：表
- 表题原文：`Table 4 Results of collaboration and non-collaboration scenario.`
- 译：协同与非协同情景的结果。
- 表头从左到右：`Non-collaboration—k | Non-collaboration—Model | Non-collaboration—TC (SEK) | Non-collaboration—Φ (SEK) | Collaboration—Without profit thresholds—Model | Collaboration—Without profit thresholds—TC (SEK) | Collaboration—Without profit thresholds—↓ (%) | Collaboration—Without profit thresholds—Φ (SEK) | Collaboration—Without profit thresholds—↑ (%) | Collaboration—With profit thresholds—TC (SEK) | Collaboration—With profit thresholds—↓ (%) | Collaboration—With profit thresholds—Φ (SEK) | Collaboration—With profit thresholds—↑ (%)`
- 数据行：8 个 company 明细行，对应 4 组模型、每组 `R` 与 `B`。
- 正文引句：`The results are summarized in Table 4.`

#### Table 5

- PDF 物理页码：12
- 类型：表
- 表题原文：`Table 5 Results with different numbers of shared customers.`
- 译：不同 shared customers 数量下的结果。
- 表头从左到右：`k | Shared customers R_s | Non-collaboration—TC (SEK) | Non-collaboration—Φ (SEK) | Collaboration—Without profit thresholds—TC (SEK) | Collaboration—Without profit thresholds—↓ (%) | Collaboration—Without profit thresholds—Φ (SEK) | Collaboration—Without profit thresholds—↑ (%) | Collaboration—With profit thresholds—TC (SEK) | Collaboration—With profit thresholds—↓ (%) | Collaboration—With profit thresholds—Φ (SEK) | Collaboration—With profit thresholds—↑ (%)`
- 数据行：8 个 company 明细行，对应 4 种 shared-customer 设置、每种 `R` 与 `B`。
- 正文引句：`Taking the result of EVRPTW of non-collaboration as the baseline, the results of different numbers of shared customers are shown in Table 5.`

#### Table 6

- PDF 物理页码：12
- 类型：表
- 表题原文：`Table 6 Results with different time window lengths.`
- 译：不同时间窗长度下的结果。
- 表头从左到右：`Instances | Non-collaboration—TC | Non-collaboration—Φ_A (SEK) | Non-collaboration—Φ_B (SEK) | Collaboration—TC (SEK) | Collaboration—↓ (%) | Collaboration—Φ_A (SEK) | Collaboration—↑ (%) | Collaboration—Φ_B (SEK) | Collaboration—↑ (%)`
- 数据行：15 行。
- 正文引句：`Table 6 demonstrates that collaboration is especially advantageous in narrow customer time windows.`

#### Table 7

- PDF 物理页码：13
- 类型：表
- 表题原文：`Table 7 Results for virtual cases with TWs.`
- 译：带 TWs 的虚拟算例结果。
- 表头从左到右：`No. customers | k | Non-collaboration—Model | Non-collaboration—TC (SEK) | Non-collaboration—Φ (SEK) | Collaboration—Model | Collaboration—TC (SEK) | Collaboration—↓ (%) | Collaboration—Φ (SEK) | Collaboration—↑ (%)`
- 数据行：6 个 company 明细行，对应 3 种 customer 数量、每种 `R` 与 `B`。
- 正文引句：`The results are shown in Table 7.`

#### Table 8

- PDF 物理页码：14
- 类型：表
- 表题原文：`Table 8 Results of for virtual cases without TWs.`
- 译：无 TWs 的虚拟算例结果。
- 表头从左到右：`No. customers | k | Non-collaboration—Model | Non-collaboration—TC (SEK) | Non-collaboration—Φ (SEK) | Collaboration—Model | Collaboration—TC (SEK) | Collaboration—↓ (%) | Collaboration—Φ (SEK) | Collaboration—↑ (%)`
- 数据行：6 个 company 明细行，对应 3 种 customer 数量、每种 `R` 与 `B`。
- 正文引句：`We present the results of such cases, as shown in Table 8.`

### 3.11 5LTEZCIB｜Xu 等 2025

#### Table 4

- PDF 物理页码：29
- 类型：表
- 表题原文：`Table 4: Case study results`
- 译：案例研究结果。
- 表头从左到右：`Provider | Initial—UC | Initial—ΣQ | Cooperative planning—UC | Cooperative planning—ΔUC | Cooperative planning—ΣQ | Cooperative planning—ΔΣQ | CPU`
- 数据行：3 行，`P1`、`P2`、`P3`。
- 正文引句：`The results are presented in Table 4.`

## 4. 效应数字表

只收录原文结果句中能确定比较分母的百分数；算法 optimality gap、运行时间改善、文献综述中转述的百分数和无法确定分母的百分数未收入。

| 条目key | 数字 | 分母（原文口径） | PDF 物理页码 | 原文句子（英文逐字） |
|---|---|---|---:|---|
| JY2IQSFS | charging costs `−5.12%`；profits `+3.96%` | `under fixed prices` 的 charging costs 与 profits | 12 | `This suggests that TOU pricing can generally lower charging costs while increasing profits, with an average reduction in charging costs of 5.12 % and an increase in profits of 3.96 %.` |
| JY2IQSFS | C-type profits `+7.25%`；emissions `−12.5%` | C-type cases 的 non-collaborative results | 13 | `In the C-type cases, participation in collaboration led to an average profit increase of 7.25 % and a carbon emissions reduction of 12.5 %.` |
| JY2IQSFS | R-type profits `+21.29%`；emissions `−17.29%` | R-type cases 的 non-collaborative results | 13 | `For the R-type cases, these figures were 21.29 % for profit increase and 17.29 % for carbon reduction.` |
| JY2IQSFS | RC-type profits `+28.07%`；emissions `−14.64%` | RC-type cases 的 non-collaborative results | 13 | `In RC-type cases, collaboration resulted in an average increase of 28.07 % in profits and a reduction of 14.64 % in emissions.` |
| JY2IQSFS | company profits `+3.46%` 至 `+28.87%`；emissions `−3.17%` 至 `−20.91%` | 每个 company 的 NCO result | 14 | `Each of the three companies experienced a profit increase ranging from 3.46 % to 28.87 %. Furthermore, carbon emissions were reduced by approximately 3.17 % to 20.91 %.` |
| JY2IQSFS | emissions `−42.78%` 至 `−61.66%`；profit differences `13.09%` 至 `23.72%` | `fleet composed of ICEVs` | 14 | `The result demonstrates that a mixed fleet can significantly reduce carbon emissions, achieving reductions ranging from 42.78 % to 61.66 %. However, this environmental benefit comes with a trade-off in terms of profit, with profit differences varying between 13.09 % to 23.72 %.` |
| LXV64TTK | carbon tax cost `−13.05%` | scenario 1 的 carbon tax cost | 19 | `Under scenario 2, one CV is replaced by two EVs, and the carbon tax cost is 13.05% lower than that in scenario 1.` |
| LXV64TTK | carbon emissions `−54.17%` | scenario 1 的 carbon emissions | 21 | `Comparing scenarios 1 and 4, the adoption of road restrictions on the accessible time windows and the bearing weight leads to carbon emission reduction of 54.17%, equal to 361.67 kg of carbon dioxide.` |
| LXV64TTK | waiting time `−57.06%` | penalty cost 0.5 时的 `27.18 min` | 21 | `Specifically, when the penalty cost increases from 0.5 to 0.6, the waiting time is reduced by 57.06% (= (27.18 min − 11.67 min)/27.18 min × 100%).` |
| FSPIDSY3 | one EV `19.08%`；two EVs `32.35%`；three EVs `32.24%`；four EVs `31.84%`；five EVs `34.89%` | `the solution with only ICEVs` 的 total cost | 17 | `In particular, when one EV is introduced in the fleet, the average improvement in the total cost with respect to the solution with only ICEVs, considering the best solutions found by ALNS, is 19.08% on average. Instead, when two, three, four, and five EVs are introduced, the percentage improvement is about 32.35%, 32.24%, 31.84% and 34.89%, respectively.` |
| FSPIDSY3 | C103 `26.2% / 25.4% / 24.8%`；C106 `21.5% / 21.8% / 21.4%` | 相同 instance、相同 LEZ customer 数下 `the solution obtained with only ICEVs` 的 total cost | 19 | `In the C-type data (Table 8), the average percentage change in the total cost with regard to the solution obtained with only ICEVs in C103 and C106 is 26.2% and 21.5% with 30 customers in the LEZ, respectively, whereas it is 25.4% and 21.8% with 20 customers in the LEZ. Finally, it is 24.8% and 21.4% with 10 customers in the LEZ.` |
| FSPIDSY3 | R102 `20.77% / 19.53% / 17.66%` | 相同 LEZ customer 数下 `solutions obtained with only ICEVs` 的 total cost | 20 | `Considering the R102 instances, the average percentage change with regard to the solutions obtained with only ICEVs is 20.77%, 19.53% and 17.66% with 30,20 and 10 customers in the LEZ, respectively.` |
| FSPIDSY3 | R107 `9.2% / 9.01% / 9.76%` | 相同 LEZ customer 数下 `the ICEV fleet` 的 total cost | 20 | `For R107, the average percentage improvement over the ICEV fleet is 9.2%, 9.01%, and 9.76% with 30,20 and 10 customers in the LEZ, respectively.` |
| FSPIDSY3 | RC103 `19.02% / 19.70% / 19.34%`；RC108 `8.40% / 9.48% / 9.49%` | 相同 LEZ customer 数下 `solutions obtained using only ICEVs` 的 total cost | 22 | `In RC103 instances, the percentage improvements with regard to the solutions obtained using only ICEVs are on average 19.02%, 19.70% and 19.34% with 30,20 and 10 customers in the LEZ respectively, whereas, in RC108, the average improvements are 8.40%, 9.48% and 9.49%, respectively.` |
| FSPIDSY3 | `11.07%` | RC103 的 ICEV-only solution total cost `2189.77` | 18 | `In this case, one ICEV (gray route) and three EVs (green dashed lines) enter the LEZ, leading to a cost reduction of 11.07%.` |
| FSPIDSY3 | one EV–one ICEV `2.02%`；two EVs `3.77%` | 相同 fleet composition、50 km range 的 base-case total cost | 22 | `The total cost is improved by 2.02% and 3.77% when the fleet comprises one EV-one ICEV and two EVs, respectively.` |
| FSPIDSY3 | `3.8%` | base case total cost | 24 | `As a result, the total cost reduces to €5.48, a 3.8% savings compared to that in the base case (see Fig. 12.b).` |
| FSPIDSY3 | `6.1%` | base case cost `€5.70` | 24 | `However, two ICEVs in the fleet compared to one in the base-case scenario travels longer total distance, resulting in a total cost of €6.05, %6.1 more than the cost of €5.70 observed in the base case.` |
| FSPIDSY3 | `31.8%` | base-case scenario total cost | 24 | `This points to 31.8% savings compared to base-case scenario, highlighting the influence of the time-window options on operating costs in last-mile deliveries.` |
| 8526FJ85 | total profit improvement `19.00%` 降至 `7.05%` | 对应 `N_L` 下 `Π_max without integrated service` | 24–25 | `The improvement in total profit decreases from 19.00 % to 7.05 % when N_L raises from 600 to 2000, implying the diminishing marginal benefits in integrating platforms and charging facilities.` |
| 8SZH92A4 | `2%`；`30%`；`more than 78%` | 各方法相对于 `the best Gini coefficient` 的 deviation | 24 | `On average, we are 2% away from the best Gini coefficient compared with 30% for the Shapley value and more than 78% for the three basic proportional rules.` |
| FQM84ZER | `14.92%` 至 `100%` | `the original profits of the current alliance consisting of all non-defaulting members` | 20 | `The value of R1, which represents the ratio of profit losses to the original profits of the current alliance, ranges from 14.92% to 100% in different default situations.` |
| 5GDKE2YV | small instances `9.00%`；large instances `11.05%` | 相应 instances 的 `initial solution without collaboration` total profit | 7 | `The results show that the average total collaboration profit is 9.00% on the small instances, and 11.05% on the large instances.` |
| JLWN3CXL | `0.95%` | best homogeneous rejection setting 的 total profit | 13 | `The heterogeneous setting with one carrier rejecting less actually yields a 0.95% larger total profit than this homogeneous setting.` |
| JLWN3CXL | `8.21%` | 不采用 overbooking 时的 carrier profit | 14 | `The best results can be achieved with CoE and β = 0.20, yielding 8.21% of additional profit for the carriers compared to not considering overbooking.` |
| JLWN3CXL | `12.29%` | 不采用 overbooking 时的 carrier profit | 14 | `In the D10 instances, the results appear similar to those with fixed revenue, with CoE achieving a 12.29% increase in profit with again β = 0.20.` |
| JLWN3CXL | `more than 75%` | 每个 carrier 的 20 个 demand instances | 16 | `Even with the adjustable profit-sharing mechanism set to ρ = 0, i.e., no profit sharing is applied, the auction outcome is positive in more than 75% of all instances for each carrier.` |
| JLWN3CXL | revenue gains `up to 15.19%`；cost savings `up to 10.43%` | `the myopic benchmark approach` 的 revenue 与 costs after auction | 19 | `Compared to the myopic benchmark approach, revenue gains of up to 15.19% and cost savings of up to 10.43% can be obtained by using our two-step policy with the respective best parameter settings.` |
| V7V84NMJ | total cost `−8%` 至 `−36%`；with time windows `−24%` 至 `−36%`；with EVs `−19%` 至 `−36%` | 对应 `non-collaboration scenarios` 的 total cost | 11 | `As shown in Table 4, collaboration reduced the total cost by 8%–36% compared to non-collaboration scenarios. These benefits were more pronounced when time windows (24%–36%) and electric vehicles (19%–36%) were taken into account.` |
| V7V84NMJ | company profits `+7%` 至 `+58%` | Table 4 中各 company 的 `Non-collaboration—Φ (SEK)` | 11 | `As shown in the last column of Table 4, the profits of companies increase by 7%–58%, which can lead to a higher willingness to collaborate.` |
| V7V84NMJ | total cost `−16%` 至 `−23%` | Table 7 中对应 `Non-collaboration—TC (SEK)` | 12–13 | `It is evident that collaboration results in significant reductions in the total costs, ranging from 16% to 23%.` |
| V7V84NMJ | total cost `approximately 20%` savings | Table 8 中对应 `Non-collaboration—TC (SEK)` | 13 | `In Table 8, it is obvious that the implementation of collaboration results in approximately 20% savings in the total costs.` |
| 5LTEZCIB | `76.91%` | provider 3 原有 `customers`（原句用语） | 28 | `After the cooperative planning, even though both providers save their unit costs (Table 4), 76.91% of customers of provider 3 shift to the coalition of provider 2.` |

## 5. 读不到／有问题的 PDF 清单

- 15 份 PDF 均可打开，均有可检索文字层，物理页码均可从封面连续核对。
- 未发现扫描件、缺失文字层或物理页码错位。
- NPDGC3FF 正文多次指向 `Table A.1` 至 `Table A.17 in Appendix A`，但本地 23 页 PDF 在 references 后结束，未包含这些 appendix tables；因此这些表无法摘录，未用正文描述替代。
- QBSC8MCD 的 Figure 2 含路线与任务重分配，但利润数字只在上一物理页正文中出现，图内没有利润数值；未把正文数字冒充为图内字段。
