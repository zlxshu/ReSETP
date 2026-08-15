# 碳强度与充电负荷图：14 篇 PDF 图表摘录

说明：页码一律为 PDF 物理页码（从附件第 1 页起数）。图题、表题和图例保留 PDF 英文原文；中文翻译另列。只记录与时间轴上的碳强度、排放因子、充电负荷、充电功率或充电时刻分布直接有关的图表。横轴为节点、可再生能源渗透率、车辆数、装机容量等而不是时间的图，不拿来替代时间轴图。

## 1. 三个问题的直接答案

### 问题一：同一时间轴上有没有同时画碳强度（或排放因子）和充电负荷（或充电功率/充电量）？

有。14 篇中有 **3 篇、10 张图命中**：

| 条目key | 图号 | PDF物理页 | 原图手法 |
|---|---:|---:|---|
| LRLMX429 | Fig. 3(b) | 8 | 双纵轴：左轴为分类型堆叠充电负荷，右轴为 `Carbon emission factor` 折线 |
| LRLMX429 | Fig. 7 | 10 | 6 个子图；每个子图双纵轴，左轴为充电负荷，右轴为 `Carbon emission factor` |
| LRLMX429 | Fig. 10 | 11 | 单图双纵轴：BSS 原始/响应后充电负荷折线 + 碳排放因子折线 |
| LRLMX429 | Fig. 12 | 11 | 上下/并列 2 个子图；每个子图双纵轴，充电负荷与碳排放因子同图 |
| WDEP8I5R | Fig. 2 | 5 | 概念示意图；充电功率需求面板与 `CO2 emissions + MEF` 面板沿同一 `t` 轴上下对齐 |
| WDEP8I5R | Fig. 4(c)–(f) | 7 | 4 个结果子图；每个子图双纵轴，`load` 与 `MEF` 共用小时轴 |
| WDEP8I5R | Fig. 5(b)–(e) | 9 | 4 个结果子图；每个子图双纵轴，`load` 与 `MEF` 共用小时轴 |
| WDEP8I5R | Fig. A1(c)–(f) | 13 | 4 个结果子图；每个子图双纵轴，`load` 与 `MEF` 共用小时轴 |
| X8VUC39Y | Fig. 3 | 8 | 上下 3 个对齐面板：EVCS Load、RES、Carbon Intensity 共用小时轴；这里的负荷是场景/观测输入，不是策略结果 |
| X8VUC39Y | Fig. 7 | 9 | 上下 3 个对齐面板：Load、RES、Carbon Intensity 共用 30 天日期轴；这里的负荷也是输入场景，不是策略结果 |

未计入命中的近似图：`LRLMX429 Fig. 8` 同时画充电负荷和碳排放因子，但横轴是 `Node`，不是时间；`4RCIC73A Figure 3(e)–(g)` 同时画平均 EV 充电和可再生发电，但没有碳强度/排放因子；`4KL9BJ6V Fig. 2 / Fig. 6(c)` 和 `V8ZHKLU3 Fig. 1(b)` 画了排放因子时间曲线，但没有同图充电负荷。

### 问题二：有没有同时画两种或以上充电策略的负荷曲线？

有。逐图命中如下（同一图中分面板对比也列入；原图图例照抄）：

| 条目key | 图号 | PDF物理页 | 图例/面板原文 |
|---|---:|---:|---|
| LRLMX429 | Fig. 3 | 8 | 面板题：`original charging load`; `charging load after implementation of demand response` |
| LRLMX429 | Fig. 7 | 10 | 工作地：`Ori`, `Dr`, `Carbon emission factor`；家庭：`Ori`, `Case1`, `Case2`, `Carbon emission factor` |
| LRLMX429 | Fig. 10 | 11 | `BSS original charge Load`, `BSS charge Load after DR`, `Carbon emission factor` |
| LRLMX429 | Fig. 12 | 11 | 工作地：`Ori`, `Dr`, `Carbon emission factor`；家庭：`Ori`, `Case1`, `Case2`, `Carbon emission factor` |
| WDEP8I5R | Fig. 2 | 5 | 面板题：`Before coordination`; `After coordination`；图例：`EV plug-in or plug-out time`, `MEF`, `CO2 emissions`, `EV charging power demand`（概念示意） |
| WDEP8I5R | Fig. 4 | 7 | 上部：`After coordination`, `fitted curve`, `Before coordination`；4 个充电剖面对应 Pareto 点 a–d；每个剖面图例为 `load`, `MEF` |
| WDEP8I5R | Fig. 5 | 9 | 同上；4 个充电剖面对应 Pareto 点 a–d；每个剖面图例为 `load`, `MEF` |
| WDEP8I5R | Fig. A1 | 13 | 同上；4 个充电剖面对应 Pareto 点 a–d；每个剖面图例为 `load`, `MEF` |
| C6TDHR7W | Fig. 4 | 10 | `RES prod. (10%)`, `Uncontrolled`, `Opt Price`, `Opt RES`, `Max RES` |
| 4KL9BJ6V | Fig. 4 | 9 | 列标题：`Uncontrolled`, `AEF 2033`, `SR-MEF 2033`, `MR-MEF, Delta=10GW`；负荷组成：`Minimally Constrained`, `SFH L2`, `MUD L2`, `Work L2`, `Public L2`, `Public L3` |
| V8ZHKLU3 | Fig. 5 | 8 | `Baseline`, `MEF`, `AEF`, `Cascading MEF` |
| X8VUC39Y | Fig. 5 | 8 | 负荷面板：`Uncoordinated`, `Optimized (flex)`, `Optimized (rw)` |
| RV2U4MB6 | Fig. 3(a) | 5 | `Before`, `After`（Home、Work、Other、Total 四个负荷面板） |
| RV2U4MB6 | Fig. 5(b) | 7 | `2018 Origin`/`2019`; `2020 Origin`/`2022`; `2023 Origin`/`2035` |
| LRQCT69L | Figure 5 | 40 | 4 个分面板：`None`, `On`, `All period`, `All period+On+Mid`；各面板有 `mean` 与 `mean±std` |
| E6MZGQ4V | Figure 3 | 26 | `existing load`, `NMH load`, `PMH load`, `AMH load` |
| E6MZGQ4V | Figure 12 | 52 | (a)–(b)：`existing load`, `NMH`, `AMH`, `PMH`；(c)：`existing load`, `20% AMH`, `60% AMH`, `100% AMH` |

`2XTT2YNI Fig. 6` 同时示意 `Smart charging` 与 `Adjusted smart charging` 的可充电时段，但不是负荷曲线，因此没有放进上表。

### 问题三：碳强度曲线是单独展示，还是和结果图合并？

- **单独展示作为输入/控制信号的数值型碳强度或排放因子曲线：2 篇。** `4KL9BJ6V Fig. 2`、`4KL9BJ6V Fig. 6(c)`；`V8ZHKLU3 Fig. 1(b)`。
- **与充电结果负荷合并：2 篇。** `LRLMX429 Fig. 3, Fig. 7, Fig. 10, Fig. 12`；`WDEP8I5R Fig. 2, Fig. 4, Fig. 5, Fig. A1`。
- **同图有充电站负荷和碳强度，但两者都是输入/场景而不是优化结果：1 篇。** `X8VUC39Y Fig. 3, Fig. 7`。
- **另有 1 篇只画年度生命周期排放因子预测，不是日内输入曲线，也没有与充电负荷合并。** `RV2U4MB6 Fig. 6(a)`。
- **没有数值型碳强度/排放因子时间曲线：8 篇。** `2XTT2YNI`, `C6TDHR7W`, `4RCIC73A`, `62C7KV3F`, `LRQCT69L`, `ZX8ZR82C`, `58N4CN2G`, `E6MZGQ4V`。其中 `C6TDHR7W Table 4` 只有年度平均排放因子表，`2XTT2YNI Fig. 6` 只有边际燃料类别示意。

## 2. 逐篇图表清单

### 1. Du 等 2025 — 条目key `LRLMX429`

#### Fig. 3

1. 条目key：`LRLMX429`
2. 图/表编号：`Fig. 3`
3. PDF 物理页码：8
4. 图题原文：`The typical EV daily charging load curve for 2023: (a) original charging load; (b) charging load after implementation of demand response.`
   译：2023 年典型 EV 日充电负荷曲线：(a) 原始充电负荷；(b) 实施需求响应后的充电负荷。
5. 横轴：`Time`；小时刻度（3AM、6AM、…、12AM），日内小时。
6. 纵轴：左轴 `EV Charge Load(kW)`，图中有 `×10^4` 倍率；(b) 另有右轴 `Carbon Emission Factor(kgCO2/kWh)`。
7. 子图：上下 2 个面板，(a) 与 (b)。
8. 线/柱与图例：(a) 5 组堆叠柱；(b) 同样 5 组堆叠柱外加 1 条碳因子线。图例：`ET slow charge`, `ET fast charge`, `Private EV work charge`, `Private EV home charge`, `Private EV fast charge`；(b) 另有 `Carbon emission factor`。
9. 图型：堆叠柱状图；(b) 为堆叠柱 + 折线双纵轴。
10. 数据来源：中国江苏省常州市；2023 年。算例使用常州 2021 年真实负荷和发电数据，动态碳排放因子由省际发电、负荷和潮流数据按碳排放流计算。

#### Table 5

1. 条目key：`LRLMX429`
2. 图/表编号：`Table 5`
3. PDF 物理页码：8
4. 表题原文：`Annual charging load and carbon reduction effects of electric vehicles in Changzhou city.`
   译：常州市电动汽车年度充电负荷与碳减排效果。
5. 横轴：年份列 `2023`, `2030`, `2035`；年度粒度。
6. 纵轴：不适用。表中行含 `Charge load (105 MWh)`, `Original carbon emission (104 tCO2)`, `Carbon emission after demand response (104 tCO2)`, `Carbon reduction rate`, `Carbon emissions/unit distance traveled (kgCO2/100 km)`, `Carbon emissions per unit of charging (kgCO2/kWh)`, 与同等汽油车比较的排放及减排率。
7. 子图：单表。
8. 线/柱：不适用；3 个年份列。
9. 图型：数据表。
10. 数据来源：中国常州市；2023 为当前算例，2030/2035 为规划情景。

#### Fig. 5

1. 条目key：`LRLMX429`
2. 图/表编号：`Fig. 5`
3. PDF 物理页码：9
4. 图题原文：`Future typical EV daily charging load curve: (a) 2030; (b) 2035.`
   译：未来典型 EV 日充电负荷曲线：(a) 2030；(b) 2035。
5. 横轴：`Time`；日内小时。
6. 纵轴：`EV Charge Load(kW)`；图中带数量级倍率。
7. 子图：并列 2 个面板。
8. 线/柱与图例：每个面板 5 组堆叠柱；`ET slow charge`, `ET fast charge`, `Private EV work charge`, `Private EV home charge`, `Private EV fast charge`。
9. 图型：堆叠柱状图。
10. 数据来源：中国常州；2030、2035 规划情景。

#### Fig. 7

1. 条目key：`LRLMX429`
2. 图/表编号：`Fig. 7`
3. PDF 物理页码：10
4. 图题原文：`Demand response for future EV slow charging at (a) workplaces for 2023; (b) home for 2023; (c) workplaces for 2030; (d) home for 2030; (e) workplaces for 2035; and (f) home for 2035.`
   译：未来 EV 慢充需求响应：(a) 2023 年工作地；(b) 2023 年家庭；(c) 2030 年工作地；(d) 2030 年家庭；(e) 2035 年工作地；(f) 2035 年家庭。
5. 横轴：`Time`；日内小时。工作地面板约为 9AM–6PM，家庭面板跨 5PM–次日 7AM。
6. 纵轴：左轴 `EV Charge Load(kW)`；右轴 `Carbon Emission Factor(kgCO2/kWh)`。
7. 子图：3×2，共 6 个面板。
8. 线/柱与图例：每个工作地面板 3 条线：`Ori`, `Dr`, `Carbon emission factor`；每个家庭面板 4 条线：`Ori`, `Case1`, `Case2`, `Carbon emission factor`。
9. 图型：双纵轴折线图。
10. 数据来源：中国常州；2023、2030、2035。

#### Fig. 10

1. 条目key：`LRLMX429`
2. 图/表编号：`Fig. 10`
3. PDF 物理页码：11
4. 图题原文：`Demand response for load charging at a BSS at node 20.`
   译：节点 20 的换电站充电负荷需求响应。
5. 横轴：`Time`；日内小时。
6. 纵轴：左轴 `BSS Charge Load(kW)`，带 `×10^4` 倍率；右轴 `Carbon Emission Factor(kgCO2/kWh)`。
7. 子图：单图。
8. 线/柱与图例：3 条线：`BSS original charge Load`, `BSS charge Load after DR`, `Carbon emission factor`。
9. 图型：双纵轴折线图。
10. 数据来源：中国常州配电网节点 20；文中该组结果为 2030 情景。

#### Fig. 12

1. 条目key：`LRLMX429`
2. 图/表编号：`Fig. 12`
3. PDF 物理页码：11
4. 图题原文：`Demand response for a scenario with low renewable energy output for 2030 for EV slow charging at the (a) workplace and (b) home.`
   译：2030 年低可再生能源出力情景下 EV 慢充需求响应：(a) 工作地；(b) 家庭。
5. 横轴：`Time`；日内小时。
6. 纵轴：左轴 `EV Charge Load(kW)`；右轴 `Carbon Emission Factor(kgCO2/kWh)`。
7. 子图：并列 2 个面板。
8. 线/柱与图例：(a) `Ori`, `Dr`, `Carbon emission factor`；(b) `Ori`, `Case1`, `Case2`, `Carbon emission factor`。
9. 图型：双纵轴折线图。
10. 数据来源：中国常州；2030 年低可再生能源出力情景。

### 2. Kang 等 2023 — 条目key `WDEP8I5R`

#### Fig. 2

1. 条目key：`WDEP8I5R`
2. 图/表编号：`Fig. 2`
3. PDF 物理页码：5
4. 图题原文：`The visualization of EV charging coordination achieved by adjusting the charging power of each EV in every time slot.`
   译：通过在每个时隙调整每辆 EV 的充电功率实现充电协调的可视化。
5. 横轴：`t`；概念时间轴，单位和粒度原文未标注。
6. 纵轴：充电面板 `power demand (kW)`；排放面板 `CO2 (g), MEF (g CO2/kWh)`。
7. 子图：左右两列 `Before coordination` / `After coordination`；每列含多辆 EV、聚合功率需求、CO2 与 MEF 的上下对齐面板。
8. 线/柱与图例：`EV plug-in or plug-out time`, `MEF`, `CO2 emissions`, `EV charging power demand`。
9. 图型：概念性的阶梯/面积式充电块、聚合功率曲线与排放/MEF 曲线组合。
10. 数据来源：示意图；原文未标注国家、电网或年份。

#### Fig. 4

1. 条目key：`WDEP8I5R`
2. 图/表编号：`Fig. 4`
3. PDF 物理页码：7
4. 图题原文：`Non-linear trade-off between daily CO2 emissions and peak power demand on a working day (2019-01-14).`
   译：工作日（2019-01-14）日 CO2 排放与峰值功率需求之间的非线性权衡。
5. 横轴：上部 Pareto 图为 `Peak power demand (kW)`；下部 4 个充电剖面为 `Hours of a day`，小时粒度显示；优化充电时隙为 15 min，MEF 为小时数据。
6. 纵轴：上部 `CO2 emissions (kg)`；下部左轴 `Power demand (kW)`，右轴 `MEF (g CO2-eq/kWh)`。
7. 子图：上部 Pareto 主图 + 拟合优度箱线图；下部 2×2 的 a–d 四个充电剖面。
8. 线/柱与图例：上部 `After coordination`, `fitted curve`, `Before coordination`；每个下部面板为 `load`, `MEF` 两条线。
9. 图型：散点 + 拟合线 + 箱线图；4 个双纵轴折线图。
10. 数据来源：美国加州；工作地停车场充电数据，日期 2019-01-14；MEF 由美国 EIA 2019 小时发电、用电和跨区交换数据计算。

#### Fig. 5

1. 条目key：`WDEP8I5R`
2. 图/表编号：`Fig. 5`
3. PDF 物理页码：9
4. 图题原文：`Non-linear trade-off between daily CO2 emissions and peak power demand on a non-working day (2019-01-12).`
   译：非工作日（2019-01-12）日 CO2 排放与峰值功率需求之间的非线性权衡。
5. 横轴：上部 Pareto 图 `Peak power demand (kW)`；下部 4 个剖面 `Hours of a day`；充电优化 15 min、MEF 小时粒度。
6. 纵轴：上部 `CO2 emissions (kg)`；下部左轴 `Power demand (kW)`，右轴 `MEF (g CO2-eq/kWh)`。
7. 子图：上部 Pareto 主图 + 拟合优度箱线图；下部 2×2 的 a–d 四个剖面。
8. 线/柱与图例：上部 `After coordination`, `fitted curve`, `Before coordination`；每个下部面板 `load`, `MEF`。
9. 图型：散点 + 拟合线 + 箱线图；4 个双纵轴折线图。
10. 数据来源：美国加州；2019-01-12；EIA 2019 电网数据与工作地充电数据。

#### Fig. A1

1. 条目key：`WDEP8I5R`
2. 图/表编号：`Fig. A1`
3. PDF 物理页码：13
4. 图题原文：`The variation in the EV charging load distribution on the Pareto front on an example day.`
   译：示例日 Pareto 前沿上 EV 充电负荷分布的变化。
5. 横轴：上部 `Peak power demand (kW)`；下部 `Hours of a day`；充电优化 15 min、MEF 小时粒度。
6. 纵轴：上部 `CO2 emissions (kg)`；下部左轴 `Power demand (kW)`，右轴 `MEF (g CO2-eq/kWh)`。
7. 子图：上部 Pareto 主图 + 拟合优度箱线图；下部 2×2 的 a–d 四个剖面。
8. 线/柱与图例：上部 `After coordination`, `fitted curve`, `Before coordination`；下部每图 `load`, `MEF`。
9. 图型：散点 + 拟合线 + 箱线图；4 个双纵轴折线图。
10. 数据来源：美国加州公共充电站 ACN-Data，2019 年；示例日具体日期原文未标注。

### 3. Zhong 等 2024 — 条目key `2XTT2YNI`

#### Fig. 6

1. 条目key：`2XTT2YNI`
2. 图/表编号：`Fig. 6`
3. PDF 物理页码：9
4. 图题原文：`Schematic diagram of basic and adjusted smart charging.`
   译：基本智能充电与调整后智能充电的示意图。
5. 横轴：水平时间顺序；无数值刻度、单位或粒度。
6. 纵轴：无数值纵轴；行标题含 `Charge time for uncontrolled charging`, `Marginal fuel type`, `Available time for smart charging`, `Smart charging`, `Adjusted smart charging`。
7. 子图：单个多行示意图。
8. 线/柱与图例：边际燃料类型图例 `C Coal`, `G Natural gas`, `R Renewable`；充电时刻用竖线/勾叉表示。
9. 图型：时间序列示意条带，不是数值负荷曲线。
10. 数据来源：示意图；原文未为本图单独标注国家、电网或年份。全文算例为美国 ERCOT、MISO、CAISO 的 2019 年情景。

### 4. Will 等 2024 — 条目key `C6TDHR7W`

#### Fig. 4

1. 条目key：`C6TDHR7W`
2. 图/表编号：`Fig. 4`
3. PDF 物理页码：10
4. 图题原文：`Average PEV-demand (lines) and RES provision (area) for a) Germany and b) France in 2030.`
   译：2030 年 (a) 德国和 (b) 法国的平均 PEV 需求（线）与 RES 供给（面积）。
5. 横轴：`Hour of day`；0–23，小时粒度。
6. 纵轴：`average PEV demand [GWh]`。
7. 子图：上下 2 个面板，德国与法国。
8. 线/柱与图例：`RES prod. (10%)`, `Uncontrolled`, `Opt Price`, `Opt RES`, `Max RES`；4 条策略线 + 1 个 RES 面积。
9. 图型：多折线 + 面积图。
10. 数据来源：PowerACE 欧洲电力市场仿真；德国、法国，2030 年。

#### Table 3

1. 条目key：`C6TDHR7W`
2. 图/表编号：`Table 3`
3. PDF 物理页码：10
4. 表题原文：`Statistics for PEV demand in Germany and France in 2030 (all values in MW).`
   译：德国和法国 2030 年 PEV 需求统计（所有数值单位为 MW）。
5. 横轴：情景与国家，年份为 2030；统计量列为 `Min`, `Median`, `Max`, `Std.dev.`。
6. 纵轴：不适用；所有数值单位 MW。
7. 子图：单表。
8. 线/柱：不适用；情景行 `Uncontrolled`, `Opt Price`, `Opt RES`, `Max RES`。
9. 图型：数据表。
10. 数据来源：PowerACE；德国、法国，2030 年。

#### Table 4

1. 条目key：`C6TDHR7W`
2. 图/表编号：`Table 4`
3. PDF 物理页码：13
4. 表题原文：`Average CO2 emission factors [kg/MWh] for France and Germany according to Eqs. (15)–(18) and (21)–(24).`
   译：依据式 (15)–(18) 和 (21)–(24) 计算的法国与德国平均 CO2 排放因子 [kg/MWh]。
5. 横轴：年份列 `2015`, `2030`，并按 PB/CB 口径列出不同排放因子。
6. 纵轴：不适用；单位 `kg/MWh`。
7. 子图：单表。
8. 线/柱：不适用；情景行包含 `No PEV`, `Uncontrolled`, `Opt Price`, `Opt RES`, `Max RES`。
9. 图型：数据表。
10. 数据来源：PowerACE；法国、德国，2015 与 2030。

### 5. Powell 等 2024 — 条目key `4KL9BJ6V`

#### Fig. 2

1. 条目key：`4KL9BJ6V`
2. 图/表编号：`Fig. 2`
3. PDF 物理页码：7
4. 图题原文：`Emission Factors (EFs) used as signals for demand optimisation: the Average Emission Factor (AEF), the Short-Run Marginal Emission Factor (SR-MEF), and the Medium-Run Marginal Emission Factor (MR-MEF) for a 10 GW demand delta and five-year period. Note: the SR-MEF and MR-MEF subplots have a different y-axis scale than the AEF subplots.`
   译：用于需求优化信号的排放因子：平均排放因子、短期边际排放因子，以及按 10 GW 需求增量和五年周期计算的中期边际排放因子。注：SR-MEF 和 MR-MEF 子图的纵轴尺度与 AEF 子图不同。
5. 横轴：`Time of Day [h]`；0–23，小时粒度。
6. 纵轴：`kg CO2/MWh`；AEF 与两种 MEF 的子图尺度不同。
7. 子图：2×3；(a)–(c) 无碳价，(d)–(f) 调度含 `100 $/tonne CO2`。
8. 线/柱与图例：每个子图含 `2023`, `2028`, `2033` 三个年份信号；图中同时有实线与点线，原图图例没有逐项注明两种线型的名称。
9. 图型：多折线图。
10. 数据来源：美国西部 WECC；电网基准资料含 EIA、EPA CEMS/eGRID、EIA-923，图示 2023、2028、2033 模型信号。

#### Fig. 4

1. 条目key：`4KL9BJ6V`
2. 图/表编号：`Fig. 4`
3. PDF 物理页码：9
4. 图题原文：`Electric vehicle charging demand is illustrated for the year 2033. SFH stands for single family home; MUD stands for multi-unit dwelling; L2 stands for Level 2 charging at 6.6 kW; and L3 stands for Level 3 charging at 150 kW.`
   译：图示 2033 年电动汽车充电需求。SFH 表示独栋住宅，MUD 表示多单元住宅，L2 表示 6.6 kW 二级充电，L3 表示 150 kW 三级充电。
5. 横轴：`Time of Day [h]`；0–24。模型控制时间步为 15 min，图以小时标度显示。
6. 纵轴：`EV Demand [GW]`。
7. 子图：8×4，共 32 个小面板；8 行为 4 种充电可达性情景在无/有碳价调度下的组合，4 列为不同控制信号。
8. 线/柱与图例：列标题 `Uncontrolled`, `AEF 2033`, `SR-MEF 2033`, `MR-MEF, Delta=10GW`；负荷组成图例 `Minimally Constrained`, `SFH L2`, `MUD L2`, `Work L2`, `Public L2`, `Public L3`。
9. 图型：分类型堆叠面积图。
10. 数据来源：美国 WECC；2033 电网情景。EV 会话来自加州湾区 2019 年充电数据。

#### Fig. 5

1. 条目key：`4KL9BJ6V`
2. 图/表编号：`Fig. 5`
3. PDF 物理页码：10
4. 图题原文：`Added emissions in each control scenario. Vertical lines at the years 2023, 2028, and 2033 indicate when the control signals were updated. Scenarios are shown with (dashed lines) and without (solid lines) the carbon price in the grid dispatch.`
   译：各控制情景的新增排放。2023、2028 和 2033 年的竖线表示控制信号更新时点。虚线表示电网调度含碳价，实线表示不含碳价。
5. 横轴：`Year`；2023–2037，年度粒度。
6. 纵轴：主图 `Added Em/added Dem [kg CO2/MWh]`；右侧小图为相对 `Flat Demand` 或 `Uncontrolled` 的归一化值。
7. 子图：4 行复合图，分别为 `Minimally constrained scenario`, `Universal Home Access charging scenario`, `High Home Access charging scenario`, `Low Home High Work Access charging scenario`；每行含主图和归一化小图。
8. 线/柱与图例：`Flat Demand`, `Uncontrolled EV Demand`, `AEF`, `SR-MEF`, `MR-MEF, Delta=5GW`, `MR-MEF, Delta=10GW`；另以实线/虚线区分无/有碳价。
9. 图型：多折线图。
10. 数据来源：美国 WECC；2023–2037 模型结果。

#### Fig. 6

1. 条目key：`4KL9BJ6V`
2. 图/表编号：`Fig. 6`
3. PDF 物理页码：11
4. 图题原文：`Sensitivity of results to extreme gas prices. The merit order is shown for a summer week in 2023 using (i) 2022 base fuel prices, (ii) 2019 base fuel prices, and (iii) 2019 base fuel prices with the carbon tax. Emissions impacts are shown for only the case of minimally constrained demand.`
   译：结果对极端天然气价格的敏感性。图示 2023 年夏季一周的优先调度顺序，分别使用 (i) 2022 基准燃料价格、(ii) 2019 基准燃料价格、(iii) 含碳税的 2019 基准燃料价格。排放影响只展示最小约束需求情景。
5. 横轴：(a)–(b) `Generation Capacity [GW]`；(c) `Time of Day [h]`，小时粒度；(d) `Year`，2023–2037。
6. 纵轴：(a) `Generation Cost [$/MWh]`；(b) `CO2 Emissions [kg/MWh]`；(c) `kg CO2/MWh`；(d) `Added Em/Added Dem [kg CO2/MWh]`。
7. 子图：4×3，共 12 个面板；3 列为三种燃料/碳价设定。
8. 线/柱与图例：(c) 信号线包括 `2023: SR-MEF`, `2033: SR-MEF`, `2023: MR-MEF, Δ=10GW`, `2033: MR-MEF, Δ=10GW`, `2023: MR-MEF, Δ=20GW`；(d) `Flat Demand`, `AEF`, `SR-MEF`, `MR-MEF, Delta=10GW`, `MR-MEF, Delta=20GW`。发电机柱按燃料类型着色。
9. 图型：发电机柱状/条带图 + 多折线图。
10. 数据来源：美国 WECC；2023 夏季周，分别用 2022/2019 燃料价格与 2019 价格加碳税；年度结果到 2037。

### 6. Martin 等 2025 — 条目key `V8ZHKLU3`

#### Fig. 1

1. 条目key：`V8ZHKLU3`
2. 图/表编号：`Fig. 1`（与本任务直接有关的是子图 b）
3. PDF 物理页码：3
4. 图题原文：`Rationale and results for failure of marginal emissions factor (MEF) managed charging at high electric vehicle (EV) adoption. a Renewable energy capacity and generator merit order for the Western Interconnection (WECC) during the first week of January 2020. The top plot shows the generator operating cost while the bottom plot shows the associated emissions, which are noisy and not correlated with cost. b Hourly MEFs and average emissions factors (AEFs) for the first week in January 2020. MEFs are noisier and larger in magnitude than AEFs. c Normalized added CO2 emissions for charging in WECC for the month of January 2020, averaged over 15 runs with error bars for +/− two standard deviations. The results show that the MEF method is not scalable to large numbers of added EVs.`
   译：高 EV 渗透率下边际排放因子管理充电失效的原因与结果。(a) 2020 年 1 月第一周 WECC 的可再生能源容量与发电机优先调度顺序；上图为运行成本，下图为相应排放。(b) 同一周逐小时 MEF 与 AEF；MEF 噪声更大且数值更高。(c) 2020 年 1 月 WECC 充电新增 CO2 排放归一化结果，为 15 次运行均值并给出正负两个标准差误差条。
5. 横轴：(b) `Date`，2020-01-06 至 2020-01-13，小时粒度。
6. 纵轴：(b) `CO2 Emissions [kg/MWh]`。
7. 子图：a、b、c 三个主部分；本任务记录 b。
8. 线/柱与图例：(b) 2 条线：`MEF`, `AEF`。
9. 图型：(b) 双折线图。
10. 数据来源：美国西部 WECC；2020 年 1 月第一周。

#### Table 1

1. 条目key：`V8ZHKLU3`
2. 图/表编号：`Table 1`
3. PDF 物理页码：6
4. 表题原文：`Emissions reductions comparison for different managed charging methods`
   译：不同管理充电方法的减排比较。
5. 横轴：情景为 `January 2020`, `January 2030`, `July 2020`, `July 2030`；每个情景按新增 EV 数量列出结果。
6. 纵轴：不适用；表中百分数为相对基准 EV 充电情景的排放减少率。
7. 子图：单表，左右各放两个月份/年份情景。
8. 线/柱：不适用；方法列 `MEF`, `Cascade (20 groups)`, `AEF`；新增 EV 行为 1,000 至 2,000,000。
9. 图型：数据表。
10. 数据来源：美国 WECC；2020 历史电网与 2030 投影情景，1 月和 7 月；每个值为 15 次试验均值。

#### Fig. 5

1. 条目key：`V8ZHKLU3`
2. 图/表编号：`Fig. 5`
3. PDF 物理页码：8
4. 图题原文：`Electric vehicle (EV) charging demand for 1 million EVs for a sample 24 hour period between January 10-11, 2020 showing baseline and the three managed charging demand profiles: marginal emissions factor (MEF), average emissions factor (AEF), and Cascading MEF methods. High charging availability can lead to spikes following the MEF method; this effect is mitigated by following the Cascading MEF method.`
   译：2020 年 1 月 10–11 日一个 24 小时样本期内，100 万辆 EV 的充电需求，展示基准以及 MEF、AEF 和级联 MEF 三种管理充电需求剖面。高充电可用性会使 MEF 方法产生尖峰，级联 MEF 可缓解该现象。
5. 横轴：`Hour`；24 小时，底层充电可用性为 15 min 数据，信号按小时更新。
6. 纵轴：`EV Charging Demand [MW]`。
7. 子图：单图。
8. 线/柱与图例：4 条线：`Baseline`, `MEF`, `AEF`, `Cascading MEF`。
9. 图型：多折线图。
10. 数据来源：美国 WECC，2020-01-10 至 2020-01-11；EV 充电会话来自加州驾驶者数据。

### 7. Silva 和 Bessa 2025 — 条目key `X8VUC39Y`

#### Fig. 3

1. 条目key：`X8VUC39Y`
2. 图/表编号：`Fig. 3`
3. PDF 物理页码：8
4. 图题原文：`Example of scenario generation, considering 500 scenarios for EVCS Load, RES generation, and Carbon Intensity for September 3rd, 2024.`
   译：2024 年 9 月 3 日 EVCS 负荷、RES 发电和碳强度的 500 个场景生成示例。
5. 横轴：`Hour`；0–23，小时粒度。
6. 纵轴：上部 `Load (kW)`；中部 `RES (kW)`；下部 `CI (gCO2/kWh)`。
7. 子图：上下 3 个共用时间轴的面板。
8. 线/柱与图例：每面板为大量 `Scenario` 线与 1 条 `Observed` 线。
9. 图型：场景束折线图。
10. 数据来源：葡萄牙北部一座超市半公共 EV 充电站；2024-09-03。碳强度由葡萄牙输电系统运营商公开的电源结构和分电源排放因子计算。

#### Fig. 5

1. 条目key：`X8VUC39Y`
2. 图/表编号：`Fig. 5`
3. PDF 物理页码：8
4. 图题原文：`Stochastic optimization results, including optimized EVCS load and charging tariffs for September 3rd, 2024, considering flexible and real-world consumers.`
   译：2024 年 9 月 3 日随机优化结果，包括在灵活消费者和真实消费者设定下优化后的 EVCS 负荷与充电电价。
5. 横轴：`Hour`；0–23，小时粒度。
6. 纵轴：上部 `Load (kW)`；下部 `Prices (€/kWh)`。
7. 子图：上下 2 个面板。
8. 线/柱与图例：负荷面板 `Uncoordinated`, `Optimized (flex)`, `Optimized (rw)`；价格面板 `Optimized (flex)`, `Optimized (rw)`, `Market Prices`。
9. 图型：负荷折线/不确定性带；价格阶梯折线。
10. 数据来源：葡萄牙北部半公共 EVCS；2024-09-03。

#### Fig. 7

1. 条目key：`X8VUC39Y`
2. 图/表编号：`Fig. 7`
3. PDF 物理页码：9
4. 图题原文：`Scenario generation of load, RES, and carbon intensity for a 30-day period.`
   译：30 天期间负荷、RES 和碳强度的场景生成。
5. 横轴：日期；2024-09-01 至 2024-10-01，底层为小时数据。
6. 纵轴：上部 `Load (kW)`；中部 `RES (kW)`；下部 `CI (gCO2/kWh)`。
7. 子图：上下 3 个对齐面板。
8. 线/柱与图例：场景线/带与观测线；本图画面没有单独显示图例文字。
9. 图型：30 天场景束/区间带 + 观测折线。
10. 数据来源：葡萄牙北部半公共 EVCS；2024 年 9 月 30 天；碳强度来自葡萄牙电源结构数据计算。

### 8. Duan 和 Motter 2025 — 条目key `4RCIC73A`

#### Figure 3(e)–(g)

1. 条目key：`4RCIC73A`
2. 图/表编号：`Figure 3`（本任务记录 e–g）
3. PDF 物理页码：21
4. 图题原文：`Annual CO2 emissions vs. renewable integration. a, Vehicle operational CO2 emissions plotted against the renewable integration level when assuming 100% vehicle electrification in the entire U.S. grid. The upper edge of the shaded area represents the CO2 emissions with the actual 2018 network capacity constraints, whereas the lower edge represents the emissions in the congestion-free case. The renewable integration level is the fraction of generation capacity powered by solar, wind, and hydroelectric plants. b-d, Breakdown of (a) into the Western (b), Texas (c), and Eastern (d) networks. The dashed lines indicate the 2018 integration levels (corresponding to a full-system integration level of 20.1%). e-g, Average EV charging (red) and renewable generation (blue) for each interconnection over a 24-hour period, where the error bars represent the standard deviation across the average day of each month over a year. The scenario assumes 100% EV penetration, no transmission constraints, and renewable integration levels of 50% for the Western interconnection (e), 60% for the Texas interconnection (f ), and 40% for the Eastern interconnection (g).`
   译：年度 CO2 排放与可再生能源接入。(e)–(g) 为三个互联系统 24 小时内的平均 EV 充电（红）和可再生发电（蓝）；误差条表示一年中各月平均日的标准差。情景假定 EV 渗透率 100%、无输电约束，西部、德州和东部互联系统的可再生能源接入率分别为 50%、60% 和 40%。
5. 横轴：`Hour`；0、6、12、18、24，小时粒度。
6. 纵轴：`Power (GW)`。
7. 子图：Figure 3 全图有 a–g；e–g 为上下 3 个日内面板，分别对应 Western、Texas、Eastern。
8. 线/柱与图例：每个面板 2 条带误差条的线；caption 指定红色为 `Average EV charging`、蓝色为 `renewable generation`。面板内没有单独图例文字。
9. 图型：带误差条的双折线图。
10. 数据来源：美国 FERC 三大互联系统；2018 电网和 EIA-930 小时负荷数据形成 12 个月平均日。

### 9. Chen 等 2025 — 条目key `62C7KV3F`

未找到符合本任务口径的图或表。该 PDF 的 Figure 2–4 展示容量投资、发电与年度排放外部性等结果，没有碳强度/排放因子时间曲线，也没有充电负荷、充电功率或充电时刻分布曲线。

### 10. Liao 等 2026 — 条目key `RV2U4MB6`

#### Fig. 2

1. 条目key：`RV2U4MB6`
2. 图/表编号：`Fig. 2`
3. PDF 物理页码：4
4. 图题原文：`Analysis of EV charging patterns in Shanghai. a Temporal distribution of charging demand across different regions. b Grid load and maximum power generation capacity of Shanghai. c Spatial distribution of charging demand across different regions and total demand. d EVs parking time in different regions. The number in the upper-right corner and the shaded area represent the decile (i.e., the 10th percentile) of parking time. e The number of stays for different EV types. CMT stands for family-used commuting, CMR for commercially used, Non-CMT for family-used non-commuting, and Semi-CMR for semi-commercially used. The number in the upper-right corner and the plum area represent the decile of parking time.`
   译：上海 EV 充电模式分析。(a) 不同区域充电需求的时间分布；(b) 上海电网负荷和最大发电容量；(c) 不同区域充电需求与总需求的空间分布；(d) 不同区域 EV 停车时间；(e) 不同 EV 类型的停留次数。
5. 横轴：(a)–(b) 从周四至周三的连续一周；原图未标注具体时间间隔；(d) `Parking time (102 min)`；(e) EV 类型。
6. 纵轴：(a) `Load (MW)`；(b) `Load (104 MW)`；(d) 分布比例/数量的原文轴标在图内，单位如前；(e) `Stays`。
7. 子图：a–e 共 5 个主部分；(c) 含多个地图。
8. 线/柱与图例：(a) `Home`, `Work`, `Other`；(b) `Real load`, `Maximum output load`；(d) 按 Home/Work/Other 展示；(e) 为 CMT、CMR、Non-CMT、Semi-CMR。
9. 图型：(a) 叠加面积/折线；(b) 双折线；(c) 地图；(d) 分布曲线；(e) 柱/点分布。
10. 数据来源：中国上海；高分辨率 EV 轨迹样本，取每车连续一周数据；年份覆盖 2018、2022、2023、2024，Fig. 2 所示合并图未为每条线单列年份。

#### Fig. 3

1. 条目key：`RV2U4MB6`
2. 图/表编号：`Fig. 3`
3. PDF 物理页码：5
4. 图题原文：`Impact of charging scheduling on charging demand. a Charging load before and after applying flexible charging scheduling. The red areas denote the grid peak load in Shanghai. The darker red region corresponds to the higher peaks (10:00 AM–4:00 PM on weekdays and 4:00–10:00 PM on weekends), while the lighter red region represents the lower peaks (7:00–9:00 PM on weekdays and 9:30 AM–12:00 PM on weekends). b The charging areas before and after applying scheduling. The blocks on the left and right represent the distribution of charging areas before and after scheduling, with the gray flow indicating the changes in the charging regions resulting from the scheduling application. c The original dispatching electricity consumption and the reduced dispatching electricity consumption after the scheduling implementation.`
   译：充电调度对充电需求的影响。(a) 灵活调度前后的充电负荷；红色区域表示上海电网峰荷时段。(b) 调度前后充电区域。(c) 原始调度用电量与实施调度后减少的调度用电量。
5. 横轴：(a) 周四至周三的连续一周；原图未标注更细粒度。
6. 纵轴：(a) `Load (MW)`。
7. 子图：a–c 三部分；(a) 为 2×2 的 Home、Work、Other、Total 负荷面板。
8. 线/柱与图例：(a) 每个面板 2 条线：`Before`, `After`，另有深/浅红峰时段阴影。
9. 图型：(a) 多折线 + 区间阴影；(b) 桑基流图；(c) 柱/分布图。
10. 数据来源：中国上海 EV 轨迹和电网峰荷时段数据；原文图内未为该周单列年份。

#### Fig. 5

1. 条目key：`RV2U4MB6`
2. 图/表编号：`Fig. 5`
3. PDF 物理页码：7
4. 图题原文：`Impact of charging scheduling on charging demand after charging station layout. a Scheduling thresholds for pre-pandemic, intra-pandemic, and post-pandemic periods (parking time and stay number). b Pre- and post-scheduling charging loads during pre-pandemic, intra-pandemic, and post-pandemic periods under a static demand scenario. c Pre- and post-scheduling charging areas during pre-pandemic, intra-pandemic, and post-pandemic periods.`
   译：充电站布局后充电调度对充电需求的影响。(a) 疫情前、疫情中和疫情后时期的调度阈值；(b) 静态需求情景下三个时期调度前后的充电负荷；(c) 三个时期调度前后的充电区域。
5. 横轴：(b) 周四至周三的连续一周；原图未标注更细粒度。
6. 纵轴：(b) `Load (kW per vehicle)`。
7. 子图：a–c 三部分；(b) 含上下 3 个时期面板。
8. 线/柱与图例：(b) `2018 Origin`, `2019`; `2020 Origin`, `2022`; `2023 Origin`, `2035`，另有峰时段阴影。
9. 图型：(b) 多折线 + 区间阴影；(a) 阈值图；(c) 流向/区域图。
10. 数据来源：中国上海；2018/2019、2020/2022、2023/2035 情景。

#### Fig. 6

1. 条目key：`RV2U4MB6`
2. 图/表编号：`Fig. 6`
3. PDF 物理页码：8
4. 图题原文：`Prediction of power mix and potential grid emission reductions by applying scheduling. a The power mix (bar) and Life-cycle CO2 emissions (curve) in East China. b Predicted emissions (line) and CO2 preventable proportions (bar). c Annual CO2 emissions before and after scheduling. d Annual reduced CO2 emissions space distribution after scheduling in 2018, 2022, 2028, and 2035.`
   译：应用调度后的电源结构预测和潜在电网减排。(a) 华东电源结构（柱）和生命周期 CO2 排放（曲线）；(b) 预测排放与可避免 CO2 比例；(c) 调度前后年度 CO2 排放；(d) 2018、2022、2028、2035 年调度后的年度 CO2 减排空间分布。
5. 横轴：(a)–(c) `Year`，2018–2035，年度粒度；(d) 年份地图。
6. 纵轴：(a) 左轴 `Ratio of different power source (%)`，右轴 `Life-cycle CO2 emission (g/kWh)`；(b) 左轴 `Preventable emission (%)`，右轴 `CO2 emission (kg vehicle−1 yr−1)`；(c) `Annual CO2 emission (103 t)`；(d) `Reduced CO2 emission (t)`。
7. 子图：a–d 共 4 个主部分。
8. 线/柱与图例：(a) 堆叠柱图例 `Hydro`, `Wind`, `Natural gas`, `Coal`, `Others`, `Nuclear`, `Solar`, `Biomass`，另有 `CO2 emission` 曲线；(b) `Before`, `After` 两条线与可避免排放柱；(c) `Before` 虚线和 `Home`, `Work`, `Other` 堆叠面积。
9. 图型：堆叠柱 + 折线双纵轴、柱线组合、年度折线、地图。
10. 数据来源：中国华东电网（含上海）；2018–2035 电源结构、用电量和输电/线损预测。

#### Fig. 7

1. 条目key：`RV2U4MB6`
2. 图/表编号：`Fig. 7`
3. PDF 物理页码：9
4. 图题原文：`Impact of the scheduling strategy on charging behaviors and extra emissions under different adoption rates and years. a Peak hours power consumption reduction. b Maximum reduction during peak hour load. c Changes in total charging loads at different adoption rates in 2018 and 2035. d Changes in the spatiotemporal distribution of charging demand at different adoption rates in 2018 and 2035. e Dispatching power consumption reduction. f Extra emission reduction.`
   译：不同采用率和年份下调度策略对充电行为及额外排放的影响。
5. 横轴：(c) 周四至周三的连续一周；(d) 空间与时间组合；其余面板为年份/采用率。
6. 纵轴：(c) `Load change (kW per vehicle)`；其余轴按各面板原文标注。
7. 子图：a–f 共 6 个主部分；(c) 含 2018 和 2035 两个周负荷子图。
8. 线/柱与图例：(c) `60%`, `100%` 两条线，并有峰时段阴影；(d) 为不同采用率的时空需求分布。
9. 图型：折线、热力图/地图及柱线组合。
10. 数据来源：中国上海；2018、2035，并模拟 20%–100% 不同采用率。

#### Fig. 8

1. 条目key：`RV2U4MB6`
2. 图/表编号：`Fig. 8`
3. PDF 物理页码：10
4. 图题原文：`Scheduling thresholds and impacts of different R parameter values. a Scheduling thresholds of scheduling within stays. b Scheduling thresholds of scheduling between stays. c Stays and charging event counts for four sample EVs. Note that colors are used only to visually distinguish consecutive stays and do not represent stay type. d Magnitude of scheduling within stays. e Magnitude of scheduling between stays. f Magnitude of total scheduling. g Reduction in dispatching power consumption.`
   译：不同 R 参数值下的调度阈值和影响。(c) 为 4 辆示例 EV 的停留与充电事件计数。
5. 横轴：(c) 为连续事件/时间顺序，原图未给数值时间单位；其余面板横轴为 `R (%)` 或车辆/阈值。
6. 纵轴：(c) 车辆类别行；其余按各面板原文标注。
7. 子图：a–g 共 7 个面板。
8. 线/柱与图例：(c) 4 行 `CMT`, `CMR`, `Non-CMT`, `Semi-CMR`；图例 `Stays`, `Charging`。
9. 图型：(c) 事件序列条带；其余为阈值/折线图。
10. 数据来源：中国上海 EV 行为样本；参数敏感性情景。

### 11. Chen 等 2024 — 条目key `LRQCT69L`

#### Figure 1

1. 条目key：`LRQCT69L`
2. 图/表编号：`Figure 1`
3. PDF 物理页码：22
4. 图题原文：`(Color Online) Normalized histogram of customer stay duration and electricity charged at rapid chargers in 2017 (U.K. Department for Transport 2018)`
   译：2017 年快速充电桩客户停留时长与充电电量的归一化直方图。
5. 横轴：(a) `Stay duration (min)`；(b) `Electricity charged (kWh)`。
6. 纵轴：两图均为 `Density`。
7. 子图：1×2；`(a) Normalized histogram of stay duration`, `(b) Normalized histogram of electricity charged`。
8. 线/柱与图例：每个面板 1 组直方柱，无图例。
9. 图型：直方图。
10. 数据来源：英国交通部快速充电桩数据，2017 年。

#### Figure 2

1. 条目key：`LRQCT69L`
2. 图/表编号：`Figure 2`
3. PDF 物理页码：23
4. 图题原文：`(Color Online) Average number of EVs at the charging station`
   译：充电站内 EV 的平均数量。
5. 横轴：`Period`；0–96，一天 96 个 15 min 时段。
6. 纵轴：`Expected number of EVs at station`。
7. 子图：单图。
8. 线/柱与图例：5 条线：`uncapacitated`, `capacitated (C = 30)`, `capacitated (C = 25)`, `capacitated (C = 20)`, `capacitated (C = 15)`。
9. 图型：多折线图。
10. 数据来源：以英国 2017 快充数据估计到达率后构造的充电站算例。

#### Figure 5

1. 条目key：`LRQCT69L`
2. 图/表编号：`Figure 5`
3. PDF 物理页码：40
4. 图题原文：`(Color Online) Electricity load under ECP-C for different compositions of the demand charge given C = 30`
   译：C=30 时，不同需量电费组成下 ECP-C 的电力负荷。
5. 横轴：`Hour`；0–24，模型为 15 min 时段。
6. 纵轴：`Load (kWh)`。
7. 子图：2×2；`(a) No demand charge`, `(b) On-peak demand charge`, `(c) All-period demand charge`, `(d) All-period, on-peak, and mid-peak demand charge`。
8. 线/柱与图例：(a) `mean (None)`, `mean±std (None)`；(b) `mean (On)`, `mean±std (On)`；(c) `mean (All period)`, `mean±std (All period)`；(d) `mean (All period+On+Mid)`, `mean±std (All period+On+Mid)`。
9. 图型：均值折线 + 标准差阴影带。
10. 数据来源：英国 2017 快充数据校准的充电站算例；需量电费时段/费率按文中美国公用事业费率结构设置。

#### Figure 8

1. 条目key：`LRQCT69L`
2. 图/表编号：`Figure 8`
3. PDF 物理页码：55
4. 图题原文：`Average number of EVs at the charging station for the long-duration charging case`
   译：长时充电情景下充电站内 EV 的平均数量。
5. 横轴：`Period`；0–96，一天 96 个 15 min 时段。
6. 纵轴：`Expected number of EVs at station`。
7. 子图：单图。
8. 线/柱与图例：4 条线：`uncapacitated`, `capacitated (C = 60)`, `capacitated (C = 50)`, `capacitated (C = 40)`。
9. 图型：多折线图。
10. 数据来源：英国快充数据构造的长时充电算例。

### 12. Wu 等 2022 — 条目key `ZX8ZR82C`

未找到可摘录图表。附件不是论文全文，而是 INFORMS 网页保存成的 5 页 PDF；只有摘要和网页导航，没有论文正文图表。该问题详见第 4 节。

### 13. Lauinger 等 2024 — 条目key `58N4CN2G`

未找到符合本任务口径的图或表。`Figure 2` 是频率偏差信号与电池 SOC 轨迹，不是充电负荷、充电功率、充电量或充电时刻分布；`Figure 7` 是调频价格时间序列，也不是碳强度/排放因子或充电负荷。

### 14. Fattahi — 条目key `E6MZGQ4V`

#### Figure 3

1. 条目key：`E6MZGQ4V`
2. 图/表编号：`Figure 3`
3. PDF 物理页码：26
4. 图题原文：`Expected EV consumption and the cumulative electricity demand`
   译：预期 EV 用电量与累计电力需求。
5. 横轴：`time`；12pm 至次日 12pm，每 3 小时一个区间。
6. 纵轴：`consumption (GWh)`。
7. 子图：1×2；`(a) EV load by NMH, PMH, and AMH participants`, `(b) Total electricity demand`。
8. 线/柱与图例：`existing load`, `NMH load`, `PMH load`, `AMH load`。
9. 图型：阶梯折线图。
10. 数据来源：美国 CAISO 2022 年 7–8 月系统负荷形成的简化日曲线；EV 参与量为文中示例构造。

#### Figure 11

1. 条目key：`E6MZGQ4V`
2. 图/表编号：`Figure 11`
3. PDF 物理页码：52
4. 图题原文：`Simulating EV drivers’ arrival and departure times and their load requirements (20% NMH, 20% AMH, and 20% PMH)`
   译：EV 驾驶者到达时间、离开时间和负荷需求的模拟（20% NMH、20% AMH、20% PMH）。
5. 横轴：`days`；0–3，小时级模拟覆盖周五至周日。
6. 纵轴：(a) `number of arrivals`；(b) `number of departures`；(c) `EV load requirement (KWh)`。
7. 子图：1×3。
8. 线/柱与图例：每个面板 3 条线：`NMH`, `AMH`, `PMH`。
9. 图型：多折线图。
10. 数据来源：美国加州；CAISO 2019-02-01 至 2019-02-03 负荷作为背景，1000 户规模；EV 到离时间与需求为模拟数据。

#### Figure 12

1. 条目key：`E6MZGQ4V`
2. 图/表编号：`Figure 12`
3. PDF 物理页码：52
4. 图题原文：`Total load after the addition of EV load: (a) EV load for 20% NMH, 20% AMH, and 20% PMH; (b) cumulative consumption; and (c) total consumption if all EV drivers participate in AMH.`
   译：加入 EV 负荷后的总负荷：(a) 20% NMH、20% AMH、20% PMH 的 EV 负荷；(b) 累计用电；(c) 所有 EV 驾驶者都参加 AMH 时的总用电。
5. 横轴：`days`；0–3，小时级。
6. 纵轴：(a) `consumption (KWh)`；(b) `cumulative consumption (KWh)`；(c) `total consumption (KWh)`。
7. 子图：1×3。
8. 线/柱与图例：(a)–(b) `existing load`, `NMH`, `AMH`, `PMH`；(c) `existing load`, `20% AMH`, `60% AMH`, `100% AMH`。
9. 图型：多折线图。
10. 数据来源：美国加州；CAISO 2019-02-01 至 2019-02-03 负荷缩放到 1000 户，EV 行为为模拟。

#### Figure 14

1. 条目key：`E6MZGQ4V`
2. 图/表编号：`Figure 14`
3. PDF 物理页码：54
4. 图题原文：`Numerical analysis of truncation`
   译：截断的数值分析。
5. 横轴：(a) `hours in the horizon (T)`；(b)–(c) `days`，0–3，小时级负荷。
6. 纵轴：(a) `% error`；(b)–(c) `consumption (KWh)`。
7. 子图：1×3；`(a) Error of Truncation`, `(b) Consumption - before`, `(c) Consumption - after`。
8. 线/柱与图例：(a) `10% AMH`, `30% AMH`, `50% AMH`；(b) `existing load`, `EV load requirement`；(c) `existing load`, `T = 2 hours`, `T = 10 hours`, `T = 18 hours`。
9. 图型：多折线图。
10. 数据来源：美国加州 CAISO 2019-02-01 至 2019-02-03 背景负荷与模拟 EV 情景。

#### Figure 15

1. 条目key：`E6MZGQ4V`
2. 图/表编号：`Figure 15`
3. PDF 物理页码：55
4. 图题原文：`Numerical analysis of linearization`
   译：线性化的数值分析。
5. 横轴：(a) `delta`（对数轴）；(b)–(c) `days`，0–3，小时级负荷。
6. 纵轴：(a) `% error`；(b)–(c) `consumption (KWh)`。
7. 子图：1×3；`(a) Error of Linearization`, `(b) Consumption - before`, `(c) Consumption - after`。
8. 线/柱与图例：(a) `10% AMH`, `30% AMH`, `50% AMH`；(b) `existing load`, `EV load requirement`；(c) `existing load`, `delta = 1E-04`, `delta = 1E-02`, `delta = 1E-01`。
9. 图型：多折线图。
10. 数据来源：美国加州 CAISO 2019-02-01 至 2019-02-03 背景负荷与模拟 EV 情景。

## 3. 效应数字表

下表只保留分母能从同一句、相邻说明或表注中确认的减排数字。百分数若是“百分点”而不是相对百分比，按原文写成百分点。引言中转述其他文献、且分母清楚的数字也如实标为“引言转述”。

| 条目key | 数字 | 分母（原文口径） | PDF物理页 | 原文那句话/表项 |
|---|---|---|---:|---|
| LRLMX429 | 5.70%（2023） | 相对 `Original carbon emission` 的年度 EV 充电碳排放 | 8 | `Carbon reduction rate 5.70 % 12.06 % 14.52 %`（Table 5；年份列依次为 2023、2030、2035） |
| LRLMX429 | 12.06%（2030） | 同上 | 8 | `Carbon reduction rate 5.70 % 12.06 % 14.52 %` |
| LRLMX429 | 14.52%（2035） | 同上 | 8 | `Carbon reduction rate 5.70 % 12.06 % 14.52 %` |
| LRLMX429 | 14.5%（正文四舍五入） | 2035 年无需求响应时的 EV 充电碳排放 | 8 | `The demand response for the carbon reduction rate is expected to reach 14.5 % by 2035.` |
| LRLMX429 | 21.79% | 无需求响应情景下集中式 BSS 的年度充电碳排放 | 10 | `Adopting the demand response model for the centralized BSS reduces the annual charging carbon emissions from 2.961 × 105 tCO2 to 2.316 × 105 tCO2, representing a reduction of 21.79 % from that of the scenario without demand response.` |
| WDEP8I5R | 20%（引言转述） | 纽约白天充电排放；夜间充电与其比较 | 3 | `Miller et al. [12] identified that overnight EV charging would generate 20% less emissions than daytime charging in New York.` |
| WDEP8I5R | 26%（引言转述） | 从最常见充电开始小时转移到最低排放因子小时之前的 EV well-to-wheel CO2 排放 | 3 | `Kang et al. [13] found that up to 26% of the well-to-wheel CO2 emissions of an EV could be reduced by shifting the charging start hour from the most common one to the hour with the minimal emissions factor according to the consumption-based method.` |
| WDEP8I5R | 13%（27.3 kg） | 示例工作日未协调充电的 CO2 排放 | 8 | `Fig. 4 illustrates that charging coordination could reduce CO2 emissions by up to 13% (27.3 kg) while maintaining the peak power demand lower than that in uncoordinated charging on this example day.` |
| WDEP8I5R | 15.7%（1.3 kg） | 示例非工作日点 a 的未协调充电 CO2 排放；点 c 为协调结果 | 8 | `Compared with point a and point c, charging coordination reduced CO2 emissions by 15.7% (1.3 kg) while maintaining peak power demand almost unchanged.` |
| WDEP8I5R | 17.7%（1.5 kg） | 示例非工作日点 a 的未协调充电 CO2 排放；点 d 不限制峰值功率 | 8 | `If peak power demand was not considered during implementing charging coordination, as indicated by point d, CO2 would be reduced by 17.7% (1.5 kg).` |
| WDEP8I5R | 18.92%（8.21 t） | 未协调充电的年度 CO2 排放 | 11 | `By maintaining the annual peak power demand unchanged compared to uncoordinated charging, charging coordination could reduce CO2 emissions by 18.92% (8.21 t) annually.` |
| WDEP8I5R | 14%（6.11 t） | 未协调充电的年度 CO2 排放；负荷上限 128 kW | 11 | `When the load limit was set to 128 kW, which is the annual base load to satisfy the whole year charging demand, charging coordination reduced around 14% of CO2 emissions annually and diminished the annual peak power demand by 60% from 314 kW to 128 kW.` |
| WDEP8I5R | 18%（7.82 t） | 未协调充电的年度 CO2 排放；负荷上限 210 kW | 11 | `By increasing the load limit from 128 kW to 210 kW, the annual CO2 emissions reduction increased from 14% (6.11 t) to 18% (7.82 t).` |
| WDEP8I5R | 1%（0.42 t，额外减排） | 未协调充电年度排放的减排百分点；负荷上限由 210 kW 提高到 387 kW | 11 | `However, further increasing the load limit by 84% from 210 kW to 387 kW to support the peak power demand could only lead to an extra 1% annual CO2 emissions reduction (0.42 t).` |
| 2XTT2YNI | 1.3%（1.6 kgCO2eq/Mm） | MISO 非受控充电下的 EV GHG 排放 | 6 | `In this case, smart charging increases EV GHG emissions by 13.4 kgCO2eq/Mm (million meters) (+13.1%) for ERCOT and reduces them by 1.6 kgCO2eq/Mm (− 1.3%) and 3.6 kgCO2eq/Mm (− 5.5%) for MISO and CAISO, respectively (Fig. 3).` |
| 2XTT2YNI | 5.5%（3.6 kgCO2eq/Mm） | CAISO 非受控充电下的 EV GHG 排放 | 6 | 同上 |
| 2XTT2YNI | 27.1%（27.5 kgCO2eq/Mm） | ERCOT 非受控充电下的 EV GHG 排放 | 9 | `However, adjusted smart charging reduces EV GHG emissions by 27.5 kgCO2eq/Mm and 47.9 kgCO2eq/Mm for ERCOT and MISO, respectively. This result corresponds to 27.1% and 37.8% reductions in EV GHG emissions for ERCOT and MISO, respectively (Fig. S14).` |
| 2XTT2YNI | 37.8%（47.9 kgCO2eq/Mm） | MISO 非受控充电下的 EV GHG 排放 | 9 | 同上 |
| C6TDHR7W | 最多 5 个百分点（>400,000 tCO2） | 法国与德国 2030 年未控制充电的消费侧（CB）碳排放 | 12 | `On average, smart charging saves up to 5%-points compared to uncontrolled charging or >400,000 tCO2 of CB carbon emissions between France and Germany in 2030.` |
| 4KL9BJ6V | 75%（引言转述） | 加州无控制充电的新增 CO2 排放 | 3 | `For example, different studies found fully managed charging could reduce added CO2 emissions for EV charging by up to 75% in California (Zhang et al., 2018) (Table IX) and up to 67% in Europe (Xu et al., 2020) (Figure 6) compared with uncontrolled.` |
| 4KL9BJ6V | 67%（引言转述） | 欧洲无控制充电的新增 CO2 排放 | 3 | 同上 |
| 4KL9BJ6V | 1.9% | 2023 年平坦需求产生的新增排放 | 8 | `The best decrease is caused by the MR-MEF 20 GW signal in the early period, with 1.9% below emissions from flat demand in 2023, and by the AEF, MR-MEF 5 GW, MR-MEF 10 GW, and MR-MEF 20 GW signals at the end of the period, with 2.1–2.2% below emissions from flat demand in 2037.` |
| 4KL9BJ6V | 2.1%–2.2% | 2037 年平坦需求产生的新增排放 | 8 | 同上 |
| 4KL9BJ6V | 5.8%–5.9% | 最小约束需求情景下的平坦需求新增排放 | 8 | `By 2037, all four signals achieve a reduction of 5.8–5.9%.` |
| 4KL9BJ6V | 1.0%–1.2% | Universal Home Access 情景的未控制充电需求 | 9 | `The Universal Home Access scenario has the highest emissions and sees larger benefits from control: without supply-side carbon pricing, the maximum reduction is 1.0–1.2% relative to uncontrolled demand, with the SR-MEF in the early period, with the AEF in the later period, and with the MR-MEF signals in both.` |
| 4KL9BJ6V | 2.3%–2.8% | Universal Home Access 情景的未控制充电需求 | 9 | `With supply-side carbon pricing, control can decrease emissions by 2.3–2.8% relative to uncontrolled and the AEF is the most consistent signal.` |
| 4KL9BJ6V | 最多 0.9%；1.8% | High Home Access 情景的未控制充电：前者无碳价，后者有碳价 | 9 | `The results for the High Home Access scenario fall between the other two: reductions of up to 0.9% without and 1.8% with carbon pricing.` |
| 4KL9BJ6V | 最多 1.8%；4.1% | 各现实 EV 情景的平坦需求：前者无碳价，后者有碳价 | 9 | `Relative to flat demand, these reductions across EV scenarios of up to 1.8% without and 4.1% with carbon pricing are smaller than the 2.2% and 5.9% possible with the minimally constrained demand.` |
| 4KL9BJ6V | 2.2%；5.9% | 最小约束需求情景的平坦需求：前者无碳价，后者有碳价 | 9 | 同上 |
| V8ZHKLU3 | 10.6%–28.3% | 基准 EV 充电产生的新增排放 | 2 | `Following the Cascading MEF method is successful across scenarios, decreasing added emissions by 10.6–28.3% and always either matching or outperforming the traditional MEF.` |
| V8ZHKLU3 | 至少 10% | 所有 4 个仿真月份、各新增 EV 数量下的基准充电新增排放 | 4 | `Following the Cascading MEF method yields at least a 10% reduction in added emissions in all four simulation months and for every number of added EVs tested and is the only method tested here that reduces emissions in all cases.` |
| V8ZHKLU3 | 26%；14.8% | 2020 年 1 月基准充电排放；分别为新增 1,000 辆和 2,000,000 辆 EV | 4 | `Specifically, in January 2020, implementing Cascading MEF with 1000 vehicles reduces emissions by 26% compared to the baseline but only yields a 14.8% reduction with 2 million added vehicles.` |
| V8ZHKLU3 | 13%–28%；10%–21% | 基准 EV 充电排放；前者为 2020，后者为 2030，最多 200 万辆 EV | 7 | `In our simulation, following the Cascading MEF method reduces emissions by 13–28% in 2020 and 10–21% in 2030 for up to 2 million vehicles.` |
| X8VUC39Y | 约 5.4%；7.9%；6.4% | 30 天 `baseline emissions`（原文用语）；依次为 monthly、dynamic、hybrid budget | 10 | `The monthly, dynamic, and hybrid strategies revealed a total of ≈ 5.4 %, 7.9 %, and 6.4 % reduction in emissions after the 30-day period.` |
| X8VUC39Y | 29.3% | 每个可行优化日的 `baseline`（原文用语）；dynamic budget | 10 | `The dynamic budget achieves the highest reduction rates per feasible day (29.3 %).` |
| X8VUC39Y | 9.4%；7.8% | 仅计找到最优解的日子，对 baseline results；依次为随机与确定性模型 | 10 | `When considering only the days where optimal solutions were found, the stochastic version of the problem proves to be beneficial, reducing emissions by 9.4 %, compared with 7.8 % for the deterministic.` |
| X8VUC39Y | 7.9%；6.2% | 完整 30 天的 baseline results；依次为随机与确定性模型 | 10 | `When considering both feasible and infeasible days (i.e., the full 30-day period), the stochastic and deterministic formulations result in an emission reduction of 7.9 % and 6.2 % and cost reduction of 11.9 % and 11.7 %, respectively.` |
| X8VUC39Y | 24% 更高 | 确定性模型每个可行日的减排率；分子为随机模型相对它的提高 | 10 | `Fig. 13 shows that the stochastic approach reaches a similar cost reduction per feasible day (≈ 2 % difference) but shows a 24 % higher emissions reduction per feasible day when compared to the deterministic.` |
| X8VUC39Y | 27.0%；29.3% | baseline emissions；依次为代理模型与 dynamic-budget 优化模型 | 12 | `Overall, the surrogate model was capable of reaching the same order of magnitude in terms of emissions (27.0 vs 29.3 %) and cost (39.3 vs 43.9 %) reduction, with only slightly lower performance, which is due to prediction errors.` |
| RV2U4MB6 | 9.99%（2022）；5.91%（2023）；7.01%（2035） | 各年调度前的年度额外 CO2 排放；调度后与之比较 | 5 | `Although the mitigation potential declined from 9.99% in 2022 to 5.91% in 2023, primarily due to spatiotemporal shifts in charging behaviors after the pandemic, the proposed scheduling strategy remains highly effective in reducing carbon dioxide emissions. By 2035, the implementation of this strategy is projected to reduce annual extra CO2 emissions per vehicle by 0.99 kg, elevating the mitigation potential to 7.01%.` |
| RV2U4MB6 | 6.92% | 2018–2035 年调度前累计额外 CO2 排放 665.82 千吨 | 5 | `The extra CO2 emissions after scheduling in 2035 amount to 48.72 thousand tons, with cumulative emissions reduced to 619.76 thousand tons (Home: 241.36 thousand tons, Work: 75.58 thousand tons, Other: 302.82 thousand tons), representing a 6.92% reduction.` |
| ZX8ZR82C | 15% | 典型夏季月份中“插枪后不延迟、尽快充电”的现行做法产生的排放 | 1 | `By using real electricity demand and generation data from the largest electricity market in the United States, we find that cost and emissions savings from smart charging are approximately 20% and 15%, respectively, during a typical summer month.` |

### Table 1 的逐行减排数值（`V8ZHKLU3`）

该表的统一分母和表注原文是：`Percentage emissions reduction for the marginal emissions factor (MEF), Cascading MEF, and average emissions factor (AEF) managed charging methods relative to the baseline electric vehicle (EV) charging case. Scenarios leading to emissions increases, instead of decreases, are denoted by values in parentheses. Values are averages of 15 trials.` 以下均在 PDF 物理第 6 页；括号项是增排，不作为减排数字列入“数字”栏，但原文表行仍保留。

| 条目key | 数字 | 分母 | PDF物理页 | 原文表行 |
|---|---|---|---:|---|
| V8ZHKLU3 | January 2020，1,000 EV：MEF 26.0%；Cascade 26.0%；AEF 0.3% | baseline EV charging case | 6 | `1000 26.0% 26.0% 0.3%` |
| V8ZHKLU3 | January 2020，100,000 EV：MEF 17.6%；Cascade 24.2%；AEF 8.6% | 同上 | 6 | `100,000 17.6% 24.2% 8.6%` |
| V8ZHKLU3 | January 2020，500,000 EV：MEF 7.0%；Cascade 23.2%；AEF 4.4% | 同上 | 6 | `500,000 7.0% 23.2% 4.4%` |
| V8ZHKLU3 | January 2020，1,000,000 EV：MEF 3.4%；Cascade 21.2%；AEF 4.6% | 同上 | 6 | `1,000,000 3.4% 21.2% 4.6%` |
| V8ZHKLU3 | January 2020，1,500,000 EV：MEF 0.3%；Cascade 17.4%；AEF 3.2% | 同上 | 6 | `1,500,000 0.3% 17.4% 3.2%` |
| V8ZHKLU3 | January 2020，2,000,000 EV：Cascade 14.8%；AEF 2.5% | 同上 | 6 | `2,000,000 (1.0)% 14.8% 2.5%` |
| V8ZHKLU3 | January 2030，1,000 EV：MEF 15.8%；Cascade 15.9%；AEF 2.0% | 同上 | 6 | `1000 15.8% 15.9% 2.0%` |
| V8ZHKLU3 | January 2030，100,000 EV：MEF 12.8%；Cascade 13.6% | 同上 | 6 | `100,000 12.8% 13.6% (0.6)%` |
| V8ZHKLU3 | January 2030，500,000 EV：MEF 3.2%；Cascade 11.3% | 同上 | 6 | `500,000 3.2% 11.3% (1.4)%` |
| V8ZHKLU3 | January 2030，1,000,000 EV：MEF 2.5%；Cascade 10.6% | 同上 | 6 | `1,000,000 2.5% 10.6% (2.5)%` |
| V8ZHKLU3 | January 2030，1,500,000 EV：MEF 1.7%；Cascade 10.6% | 同上 | 6 | `1,500,000 1.7% 10.6% (3.7)%` |
| V8ZHKLU3 | January 2030，2,000,000 EV：MEF 1.1%；Cascade 11.6% | 同上 | 6 | `2,000,000 1.1% 11.6% (2.0)%` |
| V8ZHKLU3 | July 2020，1,000 EV：MEF 28.0%；Cascade 28.3%；AEF 11.0% | 同上 | 6 | `1000 28.0% 28.3% 11.0%` |
| V8ZHKLU3 | July 2020，100,000 EV：MEF 18.1%；Cascade 24.6%；AEF 15.8% | 同上 | 6 | `100,000 18.1% 24.6% 15.8%` |
| V8ZHKLU3 | July 2020，500,000 EV：MEF 8.2%；Cascade 22.2%；AEF 15.2% | 同上 | 6 | `500,000 8.2% 22.2% 15.2%` |
| V8ZHKLU3 | July 2020，1,000,000 EV：MEF 0.7%；Cascade 22.5%；AEF 16.1% | 同上 | 6 | `1,000,000 0.7% 22.5% 16.1%` |
| V8ZHKLU3 | July 2020，1,500,000 EV：Cascade 21.6%；AEF 15.4% | 同上 | 6 | `1,500,000 (1.8)% 21.6% 15.4%` |
| V8ZHKLU3 | July 2020，2,000,000 EV：Cascade 20.3%；AEF 13.3% | 同上 | 6 | `2,000,000 (3.4)% 20.3% 13.3%` |
| V8ZHKLU3 | July 2030，1,000 EV：MEF 21.2%；Cascade 21.3%；AEF 20.2% | 同上 | 6 | `1000 21.2% 21.3% 20.2%` |
| V8ZHKLU3 | July 2030，100,000 EV：MEF 19.0%；Cascade 21.5%；AEF 13.9% | 同上 | 6 | `100,000 19.0% 21.5% 13.9%` |
| V8ZHKLU3 | July 2030，500,000 EV：MEF 11.0%；Cascade 16.8%；AEF 15.9% | 同上 | 6 | `500,000 11.0% 16.8% 15.9%` |
| V8ZHKLU3 | July 2030，1,000,000 EV：MEF 7.4%；Cascade 14.5%；AEF 14.9% | 同上 | 6 | `1,000,000 7.4% 14.5% 14.9%` |
| V8ZHKLU3 | July 2030，1,500,000 EV：MEF 5.8%；Cascade 14.4%；AEF 15.8% | 同上 | 6 | `1,500,000 5.8% 14.4% 15.8%` |
| V8ZHKLU3 | July 2030，2,000,000 EV：MEF 3.4%；Cascade 14.9%；AEF 16.8% | 同上 | 6 | `2,000,000 3.4% 14.9% 16.8%` |

## 4. 读不到 / 有问题的 PDF 清单

### `ZX8ZR82C` / 附件 `FZ5BTR9Z`

- PDF 可以打开，也有文字层，物理页码可核。
- 但附件内容是 2023-11-06 保存的 INFORMS 文章网页，共 5 页，不是 19 页论文正文。第 1 页只有摘要，第 2–5 页是文章信息、网站导航和页脚。
- 因附件本身没有论文图表，本文对该条目的逐篇清单只能写“未找到可摘录图表”；没有用网页摘要去替代图表。

### 其余 13 篇

- 均能打开，均有可检索文字层；没有扫描件。
- 图题、坐标轴和 PDF 物理页均可逐页核对。个别期刊印刷页码与 PDF 物理页不同，本报告只使用 PDF 物理页码。
