# Z5：多趟论文的车队规模设定与收益体现方式取证

任务编号：Z5  
终态：`Z5_MULTITRIP_FLEET_LITERATURE_COMPLETE`  
合格论文：7 篇  
剔除论文：5 篇  
执行边界：只做全文取证；未改模型、论文或既有项目文件，未运行实验。

## 0. 先给结论

**FACT。** 7 篇合格论文全部明确允许同一实体车在一个工作日、时间域或 period 内完成两条以上从车场出发并返回车场的配送趟；没有把单趟 EVRP、单条路线占一辆车的论文混入统计。

**INFERENCE。** 对本文最可辩护的比较合同不是把车队上限随“开启多趟”人为缩小，而是给单趟与多趟相同、来源可解释的可用车队上限，让模型决定实际启用实体车数。Zhao et al.（2024, pp. 922–923, 932–934）正是“给定可用集合 K、用 z_k 决定实际启用数”；Cueto et al.（2021, pp. 510–513）则先用多趟 VRP 需求分布形成战略车队，再在每日运营中固定该上限。两种设计都不支持本文当前无出处的 `ceil(0.25·R_d)`。

**INFERENCE。** 不应另造“每车每天最多 X 趟”。Brandão and Mercer（作者全文 pp. 2–4）、Cattaruzza et al.（作者稿 p. 1）、Cueto et al.（pp. 504, 506, 513）、Zhao et al.（pp. 922–923）和 Cavecchia et al.（pp. 114–116）都用工作日长度、车场营业时间、时间窗、前后趟不重叠及装卸时间自然限制趟数。只有 Zhen et al.（2020, pp. 12–13）在主算例显式给 3 或 5 趟上限，而且没有给业务依据，还说明最大趟数测试“没有清晰差异”。因此可直接核到的主算例数值只是 3–5，不构成可迁移的经验区间；附录的 2 趟只是教学例。

**FACT。** 若本文继续按配送趟计固定费，多趟减少实体车不会自动减少固定成本。Wang et al.（2024, p. 6, 式(1)）提供了一个同样的记账结构：`F^k` 随每个活动趟 `u` 的车场出弧计入，尽管 p. 1 的动机写的是减少车队固定成本；该式不能把实体车复用转化为固定成本节约。本文此时应报告“1040 个配送趟由 693 辆实体车完成，相对单趟 1040 辆减少 347 辆、下降 33.4%”以及复用强度，而不能报告由此产生的固定成本下降。

## 1. 取证口径与检索范围

第一轮宽检覆盖三组：经典多行程 VRP/VRPTW、多车场多趟、以及电动车多趟/异质电动车多趟。来源优先为出版社全文、机构库的 publisher PDF、作者公开全文和本地 Zotero 的出版社 PDF。第二轮逐篇核对四个必要结构：是否存在实体车索引；是否存在该实体车的第 r/u/w 趟；每趟是否从车场出发并返回；相邻趟是否由时间连续、先后或不重叠约束串到同一实体车。缺少任一关键结构且只能证明“有多条路线”的论文，均剔除。

最终合格 7 篇：经典 MTVRP 3 篇，含多车场的多趟论文 3 篇，异质电动车多趟 1 篇。逐字段的原文大意、页码、DOI、来源和全文 SHA-256 见 `qualified_papers.json`。5 篇剔除项及其单趟证据见 `excluded_papers.json`。

## 2. 第一部分：合格论文如何设定车队规模

### 2.1 Brandão and Mercer (1998), The multi-trip vehicle routing problem

**多趟成立。** 作者全文 p. 2 写明实际算法允许“一天任意数量的多趟”，并同时处理司机合法工作时长；p. 4 把 tour 定义为分给同一车辆的一组 routes，以 `h_v` 表示车辆 v 的路线数，并以各趟时间之和约束该车的正常工时与加班。

**车队规模。** 作者全文 p. 4 明说总车辆数 `V` 可以事先给定，也可以由算法确定。比较算例中不是按需求/载重推出 V，而是把 `V=1,...,V_max` 各自作为一个子问题；随后按无车辆数限制的 VRP 准最优路程 `Z*` 构造日工时 `T_1=round(1.05 Z*/V)`、`T_2=round(1.10 Z*/V)`（作者全文 p. 13）。因此算例中 V 是场景输入，和 V 联动的是工作日长度，而不是一个车队比例公式。

**总量是否随多趟缩小。** 理论比较保持每个子问题的 V 固定；实际案例叙述则引用 Burton's Biscuits 的模拟，允许第二趟后车辆需求从 21 降为 19（作者全文 p. 2）。两种合同在文中并存，作者没有给一个普适“多趟缩车系数”。

**每日趟数上限。** 实际算法为任意趟数，受司机时长和时间窗限制；无数值趟数上限（作者全文 pp. 2–4）。

### 2.2 Cattaruzza et al. (2014), A memetic algorithm for the Multi Trip Vehicle Routing Problem

**多趟成立。** 作者稿 p. 1 明确每辆车可在工作日完成若干趟，返场重装后再开始下一配送趟；同页定义车场有 `m` 辆同质车，分给同一车的所有 routes 总时长不超过工作日 `T_H`。

**车队规模。** `m` 是每个算例事先给定的输入。Taillard 基准从经典 CVRP 实例生成，对不同 m 分别构造 `T_H1=round(1.05 z*/m)`、`T_H2=round(1.10 z*/m)`，其中 `z*` 是原 CVRP 的已知解值（作者稿 p. 13）。这不是由总需求/载重直接推 m，而是扫描不同 m，并用 m 反推工作日紧度。

**总量是否随多趟缩小。** 每个算例的 m 固定，算法把多条趟分配给这 m 辆车；论文没有单趟与多趟两种合同下自动改小 m 的比较（作者稿 pp. 1, 13）。

**每日趟数上限。** 无数值上限；仅以 `T_H` 限制分给同一实体车的所有趟总时长（作者稿 p. 1）。

### 2.3 Zhen et al. (2020), Multi-depot multi-trip vehicle routing problem with time windows and release dates

**多趟成立。** p. 3 定义每个车场有自己的实体车队、每趟从同一车场出发并返回、同车各趟不得时间重叠；p. 4 的 `k,w` 变量明确表示车辆 k 的第 w 趟，并说明真实执行趟集合依次为 `{1,2}`、`{1,2,3}` 等。附录 p. 17 给出车辆 `k0` 连续执行两条 `d-c-d` 趟的实例。

**车队规模。** K 和 W 是输入集合，目标式(1)只最小化总行驶时间（pp. 3–4），不内生购买车队。p. 13 说明实例名四部分依次为客户数、车场数、总车辆数和每车最大趟数；表中常见 2 辆/车场只是表格构造模式，正文没有给需求、载重、时间窗或班次时长推导公式。

**总量是否随多趟缩小。** 每个算例固定总车辆数；Table 5 另做车辆数敏感性，但没有“开启多趟后把同一算例总量自动调小”的合同（pp. 13–14）。

**每日趟数上限。** 小型及 10–80 客户主算例为 3，90–200 客户主算例为 5（pp. 12–13）；附录例为 2（pp. 16–17）。p. 13 明说未列最大趟数测试，因为结果没有清晰差异；没有给业务依据。

### 2.4 Fermín Cueto et al. (2021), A solution approach for multi-trip vehicle routing problems with time windows, fleet sizing, and depot location

**多趟成立。** p. 504 定义一趟是实体车从车场出发、访问客户并返回；允许一车多趟。pp. 506、513 的相邻趟时序约束和 route-packing 再把多条趟装入同一实体车。

**车队规模。** 该文分战略与运营两层。战略层先模拟 50 个繁忙需求实现，每个实现求解多趟 VRP 并记录每车场车辆需求，最终取这 50 个需求值的第 95 百分位作为各场固定车队（p. 510）；需求模拟本身使用客户激活 Bernoulli 分布、活动客户需求 `Poisson(9.95)` 和校准系数 β（pp. 509–510）。这是本组唯一给出完整、可解释车队推导程序的论文。

**总量是否随多趟缩小。** 车队先按多趟运营需求设计，随后在每日运营中固定不变；p. 513 明确把集合 K 的基数设为已分配车队，实际日利用率可以下降，峰日不足时临时租车。Table 2 的 P75/P95/Max/Max+10% 对应 12/14/16/18 辆（p. 511）。

**每日趟数上限。** 没有给“最多 X 趟”。趟集合 R 只是潜在索引，实际趟数由车场营业时段 6:00–17:00、客户时间窗 8:00–16:00和前后趟时序限制（pp. 504, 506, 515）。

### 2.5 Wang et al. (2024), Heuristic Algorithms for Heterogeneous and Multi-Trip Electric Vehicle Routing Problem with Pickup and Delivery

**多趟成立。** p. 1 明写 6:00–24:00 的每日配送窗口和每车每天多趟；pp. 5–6 的变量 `x^{kg}_{iju}` 同时带实体车 g 和第 u 趟，式(7)要求同一实体车的后一趟在前一趟结束后开始。

**车队规模。** 可用总量事先给定。Table 2 对两类 EV 各给 `Max_Vehicle_Cnt=500`（p. 13），没有需求、载重、时间窗或班次时长推导，也未说明 500 的外部依据。

**总量是否随多趟缩小。** 500/类保持为可用上限，模型在其中安排实际车辆与各车的多趟；论文没有单趟—多趟同实例的车队总量比较（pp. 5–6, 13）。

**每日趟数上限。** `H^{kg}` 是实体车的趟集合，但没有给集合基数或数值上限；实际受 6:00–24:00、时间窗和式(7)时序限制（pp. 1, 5–6）。

### 2.6 Zhao et al. (2024), A hybrid genetic search and dynamic programming-based split algorithm for the multi-trip time-dependent vehicle routing problem

**多趟成立。** p. 922 定义每车在 `[E,L]` 内完成多趟，每趟从车场出发、服务客户并返回；p. 923 的 `x^{k,r,m}_{ij}` 表示实体车 k 的第 r 趟，目标中的 `z_k` 表示实体车 k 是否启用。

**车队规模。** 可用集合 `K={1,...,K}` 事先存在，但实际启用数量由 `z_k` 内生决定；目标式(1)为总趟时长加 `P∑_k z_k`（pp. 922–923）。实验没有给 K 由需求/载重推导的公式，而是直接报告解中的 `N_veh`。

**总量是否随多趟缩小。** 可用上限保持不变，实际启用实体车数下降。Table 6 在同一 10 客户数据中把 P 从 0 提至 20，`N_veh` 可从 3 降至 1，而总趟数仍为 3；正文明确解释固定费越高越倾向复用现有车辆（pp. 932–934）。

**每日趟数上限。** p. 923 只把 `R={1,...,R}` 设为“某个足够大的整数”的趟索引集，没有给每日数值；实际趟数由 `[E,L]`、容量、单趟最大距离 D 和时序决定（pp. 922–923）。

### 2.7 Cavecchia et al. (2025), A Real-World Multi-Depot, Multi-Period, and Multi-Trip Vehicle Routing Problem with Time Windows

**多趟成立。** p. 112 说明同一实体车在每个 period 可执行多趟并回到所属车场；pp. 114–116 定义一条实体车 route 可由一条或多条 trip 构成，相邻趟间加固定装卸时间 Δ，并以同一车辆的前后关系变量串联。

**车队规模。** 模型有各车型候选车辆集合 `K_v`，但实际使用车辆由 `y_{kv}` 内生选择；构造算法在没有已用车辆可接趟时才“创建新车”（p. 116）。论文未给候选总量的需求/载重推导式，报告的是解所需实体车数。

**总量是否随多趟缩小。** 不是先把车队按某个比例缩小，而是将生成的趟分配给实体车并最小化启用车成本；Table 3 逐车场、车型报告最终使用车辆数（pp. 119–120）。

**每日趟数上限。** 无数值上限；每条 route 可有一条或多条 trip，受车辆每 period 最大工时 T、客户时间窗和趟间装卸时间 Δ 限制（pp. 114–116）。

## 3. 第二部分：多趟收益在论文中体现为什么

| 论文 | 实际报告口径 | 固定成本计费单位 | 是否隔离出“多趟的因果收益” |
|---|---|---|---|
| Brandão and Mercer (1998) | 作者全文 p. 2 引用实际模拟的 21→19 辆与单位配送成本 -5%；简化算法以给定 V 下总行驶时间和车间工作量平衡为结果（pp. 3–4, 13–16） | 简化模型没有车辆固定费；实际模型列司机、燃油、车队维护和租车成本，但未给代数计费单位（p. 2） | 21→19 是引述的实际模拟；简化基准未做单趟对照 |
| Cattaruzza et al. (2014) | 总行驶时间、可行解获得率和算法解质量（作者稿 pp. 1, 15–23） | 无固定费，目标是总行驶时间（p. 1） | 否 |
| Zhen et al. (2020) | 总行驶时间与算法质量；另报告车辆数敏感性（pp. 1, 12–14） | 无车辆固定费，式(1)仅行驶时间（p. 4） | 否 |
| Fermín Cueto et al. (2021) | 车队需求、固定车队成本、峰日租车数/费用和总车辆成本；并报告日利用率风险（pp. 510–513） | 每辆被配置的实体车；日车队成本不随当日利用与否变化（pp. 506, 513），临时租车按辆·日 $90（p. 511） | 没有单趟对照，但车队设计全过程是多趟 VRP |
| Wang et al. (2024) | 总成本及行驶、等待、充电、车辆成本分项；动机写减少车队（pp. 1, 17–21） | **按活动配送趟**：式(1)对每个 `u` 的车场出弧加 `F^k`（p. 6） | 否；其固定费结构不能体现实体车复用节约 |
| Zhao et al. (2024) | 总成本、实际启用实体车数 `N_veh`、总趟数 `N_trip`；固定费提高时实际用车下降（pp. 932–934） | 每辆启用实体车 k：`P z_k`（p. 923） | 参数实验显示复用—用车—成本权衡，但不是单趟基线 |
| Cavecchia et al. (2025) | 车辆使用总成本和实际使用实体车数（pp. 115–116, 119–120） | `A_v`：一辆实体车在全部 periods 中至少使用一次；`B_v`：该实体车在一个 period 执行一条由多趟组成的 route（p. 115） | 否 |

**一句话结论。** 在真正建模实体车多趟的论文里，多趟的收益通常体现为更少的实体车/更高的车队利用率，并在固定费按实体车计时进一步体现为车队成本下降；只做算法基准的论文则多报告总行驶时间与可行性，而不是声称多趟本身带来成本下降。

## 4. 第三部分：对本文的直接含义

### 4.1 总量随多趟缩小，还是总量固定、实际用车下降？

**INFERENCE：采用“共同可用上限固定、实际启用实体车数内生下降”作为单趟—多趟对比合同。** Zhao et al.（2024, pp. 922–923, 932–934）直接采用固定可用集合 K 与内生 `z_k/N_veh`；Cueto et al.（2021, pp. 510–513）表明如果研究的是长期购置车队，可以先用多趟 VRP 的需求实现求出战略车队，再在日运营中固定；Cavecchia et al.（2025, pp. 116, 119–120）也直接报告趟聚合后实际需要的实体车。本文当前 `num_ev(d)=ceil(0.25R_d)` 既不是这三种论文中的固定可用上限，也没有像 Cueto 那样的需求分布推导，不能从本次文献取证获得支持。

这里有两个不同研究问题，不能混写：同日运行机制的因果比较应固定可用上限并比较实际用车；长期车队规划研究才允许把多趟后的所需车队另行内生设计。本文当前 1040→693 是前一种结果。

### 4.2 是否需要“每车每天最多几趟”？

**INFERENCE：在没有法规、班次或企业规则原始数据时，不需要另设数值趟数上限。** 应由当日工作域、司机/车辆最大工时、客户时间窗、充电、装卸/返场时间和前后趟不重叠共同限制。依据为 Brandão and Mercer（作者全文 pp. 2–4）、Cattaruzza et al.（作者稿 p. 1）、Cueto et al.（2021, pp. 504, 506, 513）、Zhao et al.（2024, pp. 922–923）和 Cavecchia et al.（2025, pp. 114–116）。

若实现必须给趟索引集一个有限大小，本次合格论文中只有 Zhen et al.（2020, pp. 12–13）给出主算例数值 3–5，附录例为 2（pp. 16–17）；作者未给业务依据，且 p. 13 说明最大趟数变化没有清晰差异。Zhao et al.（2024, p. 923）仅写“足够大的整数 R”。因此不能把 2–5 或 3–5 升格为本文的文献支持运营上限。

### 4.3 固定成本仍按趟计时，什么收益指标不算虚报？

**FACT。** Wang et al.（2024, p. 6）表明按每个活动趟收取 `F^k` 时，实体车从一趟复用到多趟不会减少这项固定费。相反，Zhao et al.（2024, p. 923）和 Cavecchia et al.（2025, p. 115）只有在固定费分别计到启用实体车和跨期实体车时，少用车才进入成本目标。

**INFERENCE。** 本文可如实报告四项：实际启用实体车数及降幅；每辆启用车平均配送趟数/趟车比；在相同 1040 趟下的覆盖客户或完成趟数；若行驶时间、距离或能耗确有变化，则分别报告这些运营分项。就现有零搜索证据，核心表述应是“相同 1040 个配送趟由 693 辆实体车完成，较单趟合同少 347 辆（-33.4%）；由于固定费按趟计，该复用不产生固定成本下降。”不得把 33.4% 的实体车下降改写成固定成本或总成本下降。

## 5. 被剔除论文

Schneider et al.（2014）、Hiermann et al.（2016）、Froger et al.（2022）、Wang et al.（2023）和陈婉茹等（2023）均为车队、充电或多车场方向的近邻论文，但其全文只定义一条 depot-to-depot route 对应一辆车，或明确“车辆一次派遣”；没有“同一实体车返场后再执行下一配送趟”的车—趟串接变量与时序约束。因此它们不进入 7 篇合格集合，也没有参与任何共同结论。逐篇页码与剔除理由见 `excluded_papers.json`。

## 6. 来源

- Brandão, J.; Mercer, A. (1998). *The multi-trip vehicle routing problem*. Journal of the Operational Research Society 49:799–805. DOI: [10.1038/sj.jors.2600595](https://doi.org/10.1038/sj.jors.2600595). 作者公开全文：[ResearchGate](https://www.researchgate.net/publication/317138432_The_multi-trip_vehicle_routing_problem).
- Cattaruzza, D.; Absi, N.; Feillet, D.; Vidal, T. (2014). *A memetic algorithm for the Multi Trip Vehicle Routing Problem*. European Journal of Operational Research 236:833–848. DOI: [10.1016/j.ejor.2013.06.012](https://doi.org/10.1016/j.ejor.2013.06.012). 作者稿：[CIRRELT](https://w1.cirrelt.ca/~vidalt/papers/WP_EMSE_CMP-SFL_2012-1.pdf).
- Zhen, L.; Ma, C.; Wang, K.; Xiao, L.; Zhang, W. (2020). *Multi-depot multi-trip vehicle routing problem with time windows and release dates*. Transportation Research Part E 135:101866. DOI: [10.1016/j.tre.2020.101866](https://doi.org/10.1016/j.tre.2020.101866).
- Fermín Cueto, P.; Gjeroska, I.; Solà Vilalta, A.; Anjos, M. F. (2021). *A solution approach for multi-trip vehicle routing problems with time windows, fleet sizing, and depot location*. Networks 78:503–522. DOI: [10.1002/net.22028](https://doi.org/10.1002/net.22028). Publisher PDF: [Edinburgh Research Explorer](https://www.pure.ed.ac.uk/ws/portalfiles/portal/200692297/net.22028.pdf).
- Wang, L.; Ding, Y.; Chen, Z.; Su, Z.; Zhuang, Y. (2024). *Heuristic Algorithms for Heterogeneous and Multi-Trip Electric Vehicle Routing Problem with Pickup and Delivery*. World Electric Vehicle Journal 15:69. DOI: [10.3390/wevj15020069](https://doi.org/10.3390/wevj15020069).
- Zhao, J.; Poon, M.; Tan, V. Y. F.; Zhang, Z. (2024). *A hybrid genetic search and dynamic programming-based split algorithm for the multi-trip time-dependent vehicle routing problem*. European Journal of Operational Research 317:921–935. DOI: [10.1016/j.ejor.2024.04.011](https://doi.org/10.1016/j.ejor.2024.04.011).
- Cavecchia, M.; Alves de Queiroz, T.; Lancellotti, R.; Zucchi, G.; Iori, M. (2025). *A Real-World Multi-Depot, Multi-Period, and Multi-Trip Vehicle Routing Problem with Time Windows*. ICORES 2025:112–122. DOI: [10.5220/0013153100003893](https://doi.org/10.5220/0013153100003893). Publisher PDF: [SciTePress](https://www.scitepress.org/Papers/2025/131531/131531.pdf).

## 7. 终态

`Z5_MULTITRIP_FLEET_LITERATURE_COMPLETE`
