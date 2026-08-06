# C2：MV-HGS-SP「多视角」算法机制文献依据审计

编号：`MV-AUDIT-C2-20260806`
执行：Codex（只读取证，codex 会话 `019fd5a6-78f7-75d2-8460-3ecb6ad77fb9`，任务 `task-msh3u3p2-rra4f6`）
落盘：终端 Claude（codex 沙箱对本外置盘只读，`mkdir` 与 `apply_patch` 均被拒，故由 Claude 代写）
状态：`AUDIT_COMPLETE`

> 以下为 Codex 交回的报告全文，未经改写。文中标注「需人工复核」的页码尚未独立核实，
> 引用进论文正文前必须先核。

---

## 1. 先用大白话说清楚：我们的“多视角”到底做了什么

大白话：MV-HGS-SP 不是在一个普通 HGS 里面换几个参数，而是先开三个真正独立的 PyVRP 0.12.2 HGS 搜索。HGS-F 按燃油/里程代理成本搜索，HGS-E 按线性用电量加恒功率充电代理搜索，HGS-M 按包含非线性充电、分时电价和碳机制的代理成本搜索。三个 HGS 各自产生路线后，候选路线再用完整的 ReSETP 模型复核；通过复核的路线汇入同一个 route pool，最后把来自不同视角的路线当作列，解集合划分主问题，重新组合成一组跨视角路线。当前冻结协议还包含“只接受经复核且不劣于当前最好解的结果”的单调保护。

所以，它和普通 HGS 的真正差别发生在两处。第一处在搜索生成阶段：普通 HGS 通常是在同一个目标和同一套路线评价下维护种群；经典 HGS 的两个子种群主要是“可行/不可行”分工，不是三个不同弧成本代理各自完整搜索。MV-HGS-SP 则在路线生成之前就建立了三个不同的搜索通道。第二处在路线生成之后：普通 HGS 直接从其种群中选择、教育和替换个体；MV-HGS-SP 还把三个通道的路线放入共同池，再用集合划分做一次跨视角路线重组。这个“独立代理搜索 + 路线池集合划分”才是本审计所说的组合机制。

上述操作以仓库内部的阶段收口、命名和来源登记为准：三个真实 PyVRP HGS 种群、三种代理模式、完整模型复核和跨视角 set partitioning 的定义见 [mv_hgs_sp_stage1_closeout_20260720.md](../memory/mv_hgs_sp_stage1_closeout_20260720.md#L11-L14)、[algorithm_naming_map_20260722.md](../memory/algorithm_naming_map_20260722.md#L13-L28)；来源登记明确把 route-pool set partitioning 视为已有的 hybrid-solve 思路，而不是自动获得的新颖性，见 [algorithm_source_and_license_register_20260719.md](../memory/algorithm_source_and_license_register_20260719.md#L66-L82)。

本报告严格只做文献和现有取证材料审计，不运行求解器、不做实验设计、不修改代码、实验产物或论文正文。内部检索先执行了：

    rg --files docs/handoff | rg -i 'literature|survey|zotero|evidence|benchmark'

随后使用已有的 literature/evidence 文件，并对外部论文逐篇核对 DOI、期刊卷页以及作者版中的方法章节或算法编号。按照 [user_operating_principles.md §2](../memory/user_operating_principles.md#L25-L29) 的标准，标题中出现“multi-population”“hybrid”或“set partitioning”不单独算证据；必须能指到论文实际做了什么以及方法所在页码、章节或算法。对于最终排版页码没有独立核实的文献，下面明确写出“页码未核实，需人工复核”。

## 2. 第一层：多种群、不同目标/视角或多代理成本并行搜索，再合并精英

### 2.1 直接支持“不同目标并行种群”的先例

**Berger, Barkaoui & Bräysy (2004), “A Parallel Hybrid Genetic Algorithm for the Vehicle Routing Problem with Time Windows,” Computers & Operations Research, 31(12), 2037–2053, DOI: 10.1016/S0305-0548(03)00163-1。** 论文第 2.1 节作者版 pp.4–5 明确设置两个并行种群：一个以总距离为目标，另一个以时间窗违反为目标；两个种群各自演化，在出现可行解等事件时发生交互。结论页（作者版 p.18）再次概括为围绕距离和时间窗违反的 two-population parallel co-evolution。见 [DOI](https://doi.org/10.1016/S0305-0548(03)00163-1) 和 [作者版 PDF](https://neo.lcc.uma.es/vrp/wp-content/data/articles/hybrid2.pdf)。

这已经足够证明“多个搜索种群分别追逐不同评价信号、再通过交互传递信息”不是 MV-HGS-SP 首创。它与我们的相同点是：搜索不是单通道，评价信号被拆给并行种群，种群之间有精英/可行解层面的信息交换。不同点是：Berger 的两个目标是距离与时间窗违反，不是燃油、线性电能、非线性充电/碳机制三个弧成本代理；它没有三个完整 HGS，也没有跨种群 route pool + set-partitioning 重组。因此它支持第一层的思想血缘，但不能单独支撑“我们的三视角组合是新算法”。

### 2.2 经典 HGS 的“多种群”通常不是多视角

**Vidal, Crainic, Gendreau, Lahrichi & Rei (2012), “A Hybrid Genetic Algorithm for Multidepot and Periodic Vehicle Routing Problems,” Operations Research, 60(3), 611–624, DOI: 10.1287/opre.1120.1048。** 这是 HGS 家族的权威来源之一。其作者版第 4.3 节（pp.8–10）把个体评价写成成本与多样性结合，并维护可行/不可行两个子种群；第 4.6 节（pp.14–16）说明两个子种群独立管理，再从合并的候选中选择父代。见 [INFORMS DOI 页面](https://doi.org/10.1287/opre.1120.1048) 和 [作者版 PDF](https://w1.cirrelt.ca/~vidalt/papers/HGS-CIRRELT-2011.pdf)。

这篇论文对本问题有两个作用。第一，它支撑“种群、多样性、局部搜索和精英管理”是成熟 HGS 结构。第二，它反过来说明不能把普通 HGS 的 feasible/infeasible subpopulation 直接改名为“两个视角”：那两个子群共享同一个问题目标，只承担可行性与多样性管理角色。MV-HGS-SP 的三种代理成本确实比经典 HGS 多了一层搜索通道，但“并行子群”本身不是新意。

**Vidal, Crainic, Gendreau & Prins (2014), “A Unified Solution Framework for Multi-Attribute Vehicle Routing Problems,” European Journal of Operational Research, 234(3), 658–673, DOI: 10.1016/j.ejor.2013.09.045。** 作者版第 3.1 节（p.6）给出按问题属性选择和适配路线评价组件的框架，包括 forward/backward/route-evaluation components；第 4 节（p.13）说明 UHGS 把遗传搜索、不可行解惩罚、Split 和成本/多样性种群管理统一起来；Algorithm 2（作者版 pp.14–15）给出通用 Split。见 [DOI](https://doi.org/10.1016/j.ejor.2013.09.045) 和 [作者版/补充材料入口](https://w1.cirrelt.ca/~vidalt/resources/UHGS_EC.pdf)。

它的血缘意义是：车辆路径 HGS 已经有“依据问题属性改变路线评价/解码组件”的成熟做法。与我们相同的是，都承认不同问题属性会改变搜索中的路线评价。不同的是，UHGS 是一个 HGS 框架中切换或组合评价组件，不是三个全问题 HGS 各自以不同代理成本独立跑完后再交给 route pool；其 Algorithm 2 是 giant-tour 的 Split，不是 route-history set partitioning。因此它支持“属性感知的路线评价并不新”，不支持三代理 HGS + SP 的整体新颖性。

### 2.3 多种群并行、合作协同和精英共享的成熟先例

**Lahrichi, Crainic, Gendreau, Rei, Crişan & Vidal (2015), “An integrative cooperative search framework for multi-decision-attribute combinatorial optimization: Application to the MDPVRP,” European Journal of Operational Research, 246(2), 400–412, DOI: 10.1016/j.ejor.2015.05.007。** 作者版第 2–3 节（pp.2–11）描述多个独立线程分别处理决策属性子集，中央记忆保存 elite/context 信息，integrator 把部分解或不同线程的信息组合起来；第 3.2–3.3 节（pp.9–11）进一步说明 partial solvers 与 integrators 的协作。MDPVRP 应用部分在作者版 pp.16–18。见 [DOI](https://doi.org/10.1016/j.ejor.2015.05.007) 和 [作者版 PDF](https://www.cirrelt.ca/documentstravail/cirrelt-2012-42.pdf)。

它与我们的共同点是“多个具有不同职责或属性焦点的搜索线程 + 中央精英/信息整合”。不同点是其线程处理的是决策属性子问题和部分解，并非三个完整的 VRP HGS 都对同一完整解空间使用不同弧成本代理；整合也不是我们的 route pool 集合划分主问题。它是第一层很强的结构先例，却不构成三视角实例的逐字复制。

**Zhou, Baldacci, Vigo & Wang (2018), “A Multi-Depot Two-Echelon Vehicle Routing Problem with Delivery Options Arising in the Last Mile Distribution,” European Journal of Operational Research, 265(2), 765–778, DOI: 10.1016/j.ejor.2017.08.011。** 第 3 节及 Algorithm 1 采用 hybrid multi-population genetic approach：初始种群被分成多个子种群，各自演化，按 ISHARE 周期共享最好个体；第 3.7.2 节明确描述多个可行子种群与不可行子种群的独立管理和最优个体共享，第 4.3.2 节讨论其相对 HGSADC 的差别。见 [DOI](https://doi.org/10.1016/j.ejor.2017.08.011) 和 [作者版 PDF](https://research.vu.nl/ws/files/212291002/A_Multi_Depot_Two_Echelon_Vehicle_Routing_Problem_with_Delivery_Options_Arising_in_the_Last_Mile_Distribution.pdf)。

这证明 EJOR 级别论文已经使用“多个子种群并行演化、共享最好个体”的结构。不同点是其子种群服务于可行性/问题结构管理，目标函数并没有拆成我们的燃油、线性电能、非线性充电碳三种代理，也没有 route pool + SP。它支持多种群和精英共享的成熟性，不能支撑三代理视角的独创性。

**Oliveira, Enayatifar, Sadaei, Guimarães & Potvin (2016), “A Cooperative Coevolutionary Algorithm for the Multi-Depot Vehicle Routing Problem,” Expert Systems with Applications, 43, 117–130, DOI: 10.1016/j.eswa.2015.08.030。** 第 2 节（作者版 pp.4–6）把每个种群作为问题一部分的解表示，部分解组合成完整解并产生反馈；第 4 节（pp.8–11）按 depot 构造和协作种群；第 5.6 节（pp.17–20）维护 elite complete solutions 并用它们更新协作过程。见 [DOI](https://doi.org/10.1016/j.eswa.2015.08.030) 和 [作者版 PDF](https://www.cirrelt.ca/documentstravail/cirrelt-2016-08.pdf)。

它与我们的相同点是多种群、独立演化、组合完整解和保留精英。不同点是其种群对应 depot/部分解的分解，不是三个对完整 VRP 使用不同标量弧成本的 HGS；它也没有集合划分路线池。它支持 cooperative coevolution 的血缘，但不能支撑我们的具体算法贡献。

**Jin, Crainic & Løkketangen (2014), “A Cooperative Parallel Metaheuristic for the Capacitated Vehicle Routing Problem,” Computers & Operations Research, 44, 33–41, DOI: 10.1016/j.cor.2013.10.004。** 第 2 节和 Algorithm 1 描述多个并行 TS 线程，其中有的线程强化、有的线程多样化，并通过异步 common solution pool 共享信息。见 [DOI/期刊记录](https://doi.org/10.1016/j.cor.2013.10.004) 和 [作者版 PDF](https://www.cirrelt.ca/documentstravail/cirrelt-2012-46.pdf)。

它支持“并行搜索线程 + 共享解池”在 VRP 元启发式中是成熟工程结构；不同点是单一目标下的 TS 协作，不是三种成本代理的 HGS，也不是 route pool 的集合划分精确重组。因此只能支撑第一层的家族先例。

**He, Hao & Wu (2025 online; 2026 print), “A Hybrid Genetic Algorithm with Multi-population for Capacitated Location Routing,” INFORMS Journal on Computing, 38(3), 829–843, DOI: 10.1287/ijoc.2023.0416。** 作者版第 3.2.2 节 p.12 按 depot configuration 组织多个子种群，并在各子种群中进行 crossover、local search 和 mutation；官方记录给出最终卷期页码 38(3):829–843。见 [INFORMS DOI 页面](https://doi.org/10.1287/ijoc.2023.0416) 和 [作者版 PDF](https://leria-info.univ-angers.fr/~jinkao.hao/papers/HeHaoWuJOC2025.pdf)。这里的最终排版页码映射未独立核对，需人工复核；方法位置以作者版 §3.2.2 p.12 为准。

这是比一般会议论文更接近目标期刊层级的近期多种群先例。它与我们相同的是多子种群、独立演化和混合遗传搜索；不同点是一个成本函数下按 depot configuration 分群，没有三种弧成本代理，也没有 route pool SP。因此它不能把 MV-HGS-SP 的组合提升为新算法原则。

### 2.4 目标期刊中的相邻表达

**陈雨蝶、干宏程、程亮、温金鹏 (2025 online),《双碳背景下复杂冷链物流模型及求解算法》,《系统工程理论与实践》, DOI: 10.12011/SETP2024-2027。** 这是本项目内部作为结构参照的目标期刊文章。其 PDF 第 3.2 节步骤 2、4–7（打印 pp.8–9）写明多种群初始化、独立进化、迁移、不同交叉/变异概率和 VNS；引言 p.3 与结论 p.21 也把 multi-population parallel evolution 与 VNS 作为算法组成。见 [DOI](https://doi.org/10.12011/SETP2024-2027)。

该文说明在目标期刊语境中，“多种群并行 + 混合局部搜索”是可以使用的算法表达，但它没有三种代理成本，也没有 route pool + set partitioning。因此它是目标期刊层级的相邻先例，不是对 MV-HGS-SP 具体机制的支持。该文目前为网络首发，正式卷期和页码尚未分配，需人工复核；上述页码是内部保存 PDF 的打印页和节号。

### 2.5 第一层小结

**FACT：** 高质量 VRP/元启发式文献已经成熟支持以下家族做法：多个种群或线程并行搜索；不同种群追逐不同目标、可行性或问题属性；通过共享最好个体、中央记忆、部分解组合或公共解池交流。

**FACT：** 在本次逐篇核对的文献中，尚未找到一篇同时明确写出“3 个完整独立 HGS + 燃油/线性电能/非线性充电碳三种弧成本代理 + 搜索后跨视角集合划分”的完全同构流程。这个“未找到”只表示本次高质量、可核实文献范围内没有找到逐字同构先例，不是把检索范围外的所有论文都证明为不存在。

**INFERENCE：** 因此，第一层可以支持 MV-HGS-SP 的机制血缘，但不能支持“多视角并行搜索”作为一般算法思想的新颖性。三个代理的具体物理含义是应用实例差异；要把它升格为算法贡献，不能只靠“用了三个视角”这个名称。

## 3. 第二层：route pool + set partitioning 精确重组在 VRP 中的地位

这里必须把“精确”说清楚：对一个已经收集的有限 route pool 解集合划分，若 MIP 在该有限列集上求到最优，则是对该有限池的精确组合；它不是对完整、无限或未生成的所有可行路线集合求全局最优。若实际运行使用 time limit，只能把得到的 incumbent 作为时间受限主问题结果，不能把它写成全局最优。这个区分是组件语义，不是措辞问题。

### 3.1 路线池和受限集合划分的标准出处

**Subramanian, Uchoa & Ochi (2013), “A Hybrid Algorithm for a Class of Vehicle Routing Problems,” Computers & Operations Research, 40(10), 2519–2531, DOI: 10.1016/j.cor.2013.01.013。** 第 3.1 节（作者版 pp.4–5）由 ILS-RVND 产生局部最优解，把其中路线按阈值放入 RoutePool；第 3.2 节（pp.5–6）给出 set-partitioning formulation，使每个客户恰好被覆盖一次并满足车队/仓库约束；Algorithm 1（作者版 p.6）用受限 MIP 调用 SP，并通过 incumbent callback 与 ILS 交互；第 3.3 节（pp.6–7）讨论每次 ILS 迭代调用或周期调用 SP 的权衡。见 [DOI](https://doi.org/10.1016/j.cor.2013.01.013) 和 [作者版 PDF](https://luizsatoru.github.io/conteudo/artigos/COR2013-ANAND.pdf)。

这篇论文几乎直接给出 route pool + SP 的标准模板：启发式负责造路线，路线进入池，SP 负责从池中选一组互不冲突且覆盖客户的路线；MIP 还可以把组合结果反馈给启发式。它没有多视角，但已经足以说明“路线池之后用集合划分重组”不是 MV-HGS-SP 新发明的组件。

**Penna, Subramanian, Ochi, Vidal & Prins (2019), “A Hybrid Heuristic for a Broad Class of Vehicle Routing Problems with Heterogeneous Fleet,” Annals of Operations Research, 273(1–2), 5–74, DOI: 10.1007/s10479-017-2642-9。** 摘要和第 1 节说明 HILS-RVRP 把 ILS、RVND 与 SP 结合，ILS 产生路线池，MIP 负责从路线池选择组合；第 4 节及 Algorithms 1–3 给出 HILS、route-pool 管理、SolveSP 和受时间限制的 MIP/启发式交互。见 [DOI](https://doi.org/10.1007/s10479-017-2642-9) 和 [作者版/开放版本](https://arxiv.org/abs/1803.01930)。

这篇长篇异构车队论文把 route pool + SP 推到了更丰富的 VRP 约束中，并不是一次性的“把一个 MIP 放在算法最后”，而是把路线池和主问题作为混合求解结构的一部分。它没有多视角 HGS，但进一步证明第二层组件是成熟标准件。

### 3.2 直接把搜索历史路线交给 SP 的高质量 VRP 先例

**Hiermann, Hartl, Puchinger & Vidal (2019), “Routing a Mix of Conventional, Plug-in Hybrid, and Electric Vehicles,” European Journal of Operational Research, 272(1), 235–248, DOI: 10.1016/j.ejor.2018.06.025。** 这是本审计最重要的近邻文献。第 4 节（作者版 pp.4–7）采用分层路线评价：上层 HGA 搜索客户分配/顺序，下层用 RCSPP/DP 和贪心方式评价燃油、插电混合和电动车路线；第 5 节（作者版 p.8 起）在 HGA 中加入 SP，用搜索历史中的路线进行重组，并同时维护可行/不可行子种群；第 5.1 节（p.9）说明路线和成本/多样性管理，第 6.3 节（p.13）做组件消融，完整方法包含 crossover、LNS 和 SP。见 [DOI/期刊页面](https://doi.org/10.1016/j.ejor.2018.06.025) 和 [作者版记录](https://www.researchgate.net/publication/325808705_Routing_a_Mix_of_Conventional_Plug-in_Hybrid_and_Electric_Vehicles)。

它和 MV-HGS-SP 的相同点非常具体：都在有不同车辆/能源机制的 VRP 中先进行高质量搜索和路线评价，再把搜索中保留下来的高质量路线交给 SP 重组。不同点也必须说清：Hiermann 等人不是三个独立的 HGS，不是三种代理成本各自完整收敛后再合并，而是在一个 HGA 中使用分层路线评价、LNS 和搜索历史路线池，并保留经典的可行/不可行子种群。因此它不是 MV-HGS-SP 的逐行复制，却足以击穿“搜索视角 + 历史路线池 + SP 重组”这个组合本身的新颖性。

**Alvarenga, Mateus & de Tomi (2007), “A Genetic and Set Partitioning Two-Phase Approach for the Vehicle Routing Problem with Time Windows,” Computers & Operations Research, 34(6), 1561–1584, DOI: 10.1016/j.cor.2005.07.025。** 论文摘要说明 GA 中间解产生的路线被加入集合 T，遗传/禁忌过程结束或达到条件后，用 CPLEX 解 set partitioning 选出最佳路线组合。见 [DOI/ScienceDirect](https://doi.org/10.1016/j.cor.2005.07.025)。最终方法小节的具体页码本次未从可访问版本独立核实，需人工复核；这里仅把卷页 1561–1584、摘要所述的“GA 产生路线集 + SP 组合”作为补充证据，不把它作为唯一判定依据。

### 3.3 第二层小结

**FACT：** route pool + restricted set partitioning 在 VRP 混合启发式中至少有 COR、EJOR、Annals of Operations Research 等多篇代表性论文；它可以承担路线组合、车辆/仓库覆盖约束和启发式反馈。

**FACT：** Subramanian (2013) 和 Penna et al. (2019) 已把该组件作为成熟 hybrid solve 结构；Hiermann et al. (2019) 还在能源/异构车辆 VRP 中把搜索历史路线送入 SP。

**INFERENCE：** 因此，MV-HGS-SP 中“把三路搜索得到的路线放进池，再用集合划分选组合”在组件层面属于成熟标准件。即使池来自三个不同代理，集合划分本身也没有因此变成新组件。

## 4. 第三层：把第一层和第二层组合成“多视角 + 精确重组”，在目标期刊层级是否有可比先例

### 4.1 与 MV-HGS-SP 的逐步骤对照

把候选贡献拆成四个必要条件：

1. 多个独立搜索通道，而不是一个 HGS 中可行/不可行两个管理子群；
2. 每个通道有不同的目标、属性或弧成本代理；
3. 通道产生的路线在搜索过程中或搜索后进入共同 route pool；
4. 用 set partitioning 对路线池做精确或受限精确重组。

文献对应关系如下。

- 条件 1 和 2 的家族先例：Berger et al. (2004) 的距离/时间窗违反双种群；Lahrichi et al. (2015) 的多线程多决策属性协作；Zhou et al. (2018)、He et al. (2025 online/2026 print) 的多种群混合遗传搜索。
- 条件 3 和 4 的成熟先例：Subramanian et al. (2013)、Penna et al. (2019)、Alvarenga et al. (2007) 的 route pool + SP。
- 四个条件中最接近整体结构的高质量先例：Hiermann et al. (2019)。它将能源/车辆相关的分层路线评价、HGA/LNS 和搜索历史路线的 SP 重组放在同一个 VRP 求解框架中。它缺少“三个独立代理 HGS”这一具体外壳，但已经有了“问题机制视角/分层路线评价 + 搜索路线池 + SP 重组”的核心数据流。

### 4.2 “完全相同”未找到，不等于“贡献成立”

本次没有找到一篇高质量论文逐字同时满足“三个完整 HGS、三种指定弧成本代理、完整模型复核、跨视角 route-pool SP”。这可以支持一个很窄的事实：MV-HGS-SP 的具体工程装配在本次检索样本中没有被找到一篇完全同构论文。

但它不能自动推出算法创新。原因是：论文贡献的判断不是看组件排列是否从未以同样的数字出现，而是看是否提出了文献中没有的搜索机制、信息流或可解释的决策作用。把两个成熟结构串起来——并行/多视角搜索与路线池集合划分——再把“两个”换成“三个”、把代理具体化为燃油/线性电能/非线性充电碳，属于应用特定的实现装配。现有文献已经分别给出并行不同评价搜索、属性协同、精英交换和路线池 SP；Hiermann et al. (2019) 还给出了同一能源车辆问题中的整体近邻。

这不是说三种代理永远不可能产生有效的应用结果；本报告没有进行性能归因，也不把运行状态当作文献证据。这里的结论仅限于：在“算法机制本身是否足够新”的门槛下，现有文献不能支持把这套组合当作独立算法贡献。

### 4.3 目标期刊层级的结论

在 Operations Research、European Journal of Operational Research、Computers & Operations Research、INFORMS Journal on Computing 等层级，审稿人已经能看到：

- parallel/cooperative multi-population search：Berger (COR 2004)、Lahrichi et al. (EJOR 2015)、Zhou et al. (EJOR 2018)、He et al. (IJOC 2025 online/2026 print)；
- problem-attribute-aware or layered route evaluation：Vidal et al. (EJOR 2014)、Hiermann et al. (EJOR 2019)；
- route-pool + set-partitioning recombination：Subramanian et al. (COR 2013)、Penna et al. (ANOR 2019)、Hiermann et al. (EJOR 2019)、Alvarenga et al. (COR 2007)。

所以，第三层的答案不是“完全没有相似论文”，而是“完整同构实例未找到，但构成贡献点所需的每个原则和最接近的组合先例都已存在”。这已经足以否定“多视角 + 精确重组”作为单独方法学贡献的说法。

## 5. 汇总表

| 文献 | 期刊/年份 | 它做了什么 | 与我们的多视角相同点 | 不同点 | 能不能支撑我们的主张 |
|---|---|---|---|---|---|
| Berger, Barkaoui & Bräysy (2004), “A Parallel Hybrid Genetic Algorithm for the VRPTW” ([DOI](https://doi.org/10.1016/S0305-0548(03)00163-1)) | Computers & Operations Research 31(12), 2037–2053；§2.1 作者版 pp.4–5，结论 p.18 | 两个并行种群分别优化距离和时间窗违反，并在可行解事件下交互 | 多评价信号、并行种群、精英/可行信息交换 | 两个种群；目标是距离/违反，不是三种能源碳弧代理；无 route-pool SP | 支撑“并行多评价搜索是成熟先例”；不支撑三视角组合新颖 |
| Vidal, Crainic, Gendreau, Lahrichi & Rei (2012), “A Hybrid Genetic Algorithm for Multidepot and Periodic VRP” ([DOI](https://doi.org/10.1287/opre.1120.1048)) | Operations Research 60(3), 611–624；§§4.3、4.6，作者版 pp.8–10、14–16 | HGS 维护可行/不可行子种群，结合成本与多样性管理个体 | 多种群、精英管理、种群合并/选择 | 两个子群共享同一目标，功能是可行性/多样性；无代理视角、无 SP | 支撑 HGS 血统；反而说明普通 HGS 子群不等于多视角 |
| Vidal, Crainic, Gendreau & Prins (2014), “A Unified Solution Framework for Multi-Attribute VRP” ([DOI](https://doi.org/10.1016/j.ejor.2013.09.045)) | European Journal of Operational Research 234(3), 658–673；§3.1 p.6，§4 p.13，Algorithm 2 pp.14–15 | 按 VRP 属性选择/适配路线评价组件，并统一 HGS、Split、局部搜索和多样性 | 属性感知评价、不同问题机制进入搜索 | 组件在一个 UHGS 中切换/组合，不是三个独立 HGS；Algorithm 2 是 Split，不是历史路线 SP | 支撑“属性/评价代理不是新思想”；不支撑我们的整体贡献 |
| Lahrichi, Crainic, Gendreau, Rei, Crişan & Vidal (2015), “An integrative cooperative search framework…” ([DOI](https://doi.org/10.1016/j.ejor.2015.05.007)) | European Journal of Operational Research 246(2), 400–412；作者版 §§2–3，pp.2–11，应用 pp.16–18 | 多线程按决策属性处理子问题，中央记忆和 integrator 组合部分解/精英 | 独立搜索、不同属性焦点、中央精英和组合 | 是属性子问题/部分解协同，不是三种完整弧成本 HGS；无 route-pool SP | 支撑多视角式合作搜索家族；不支撑具体创新 |
| Zhou, Baldacci, Vigo & Wang (2018), “A Multi-Depot Two-Echelon VRP…” ([DOI](https://doi.org/10.1016/j.ejor.2017.08.011)) | European Journal of Operational Research 265(2), 765–778；§3、Algorithm 1、§3.7.2、§4.3.2 | 多个子种群独立演化，按周期共享最好个体，并管理可行/不可行群 | 多种群并行和精英共享 | 分群服务问题结构/可行性，不是三代理成本；无 SP | 支撑多种群成熟性；不支撑三视角+SP 新颖 |
| Oliveira, Enayatifar, Sadaei, Guimarães & Potvin (2016), “A Cooperative Coevolutionary Algorithm…” ([DOI](https://doi.org/10.1016/j.eswa.2015.08.030)) | Expert Systems with Applications 43, 117–130；§2 pp.4–6，§4 pp.8–11，§5.6 pp.17–20 | 按 depot/部分问题建立种群，组合部分解，维护 elite complete solutions | 独立种群、协同组合、精英保留 | 种群是部分解分解，不是同一完整 VRP 的不同弧成本 HGS；无 SP | 支撑 cooperative coevolution 先例；不支撑我们的机制为新 |
| Jin, Crainic & Løkketangen (2014), “A Cooperative Parallel Metaheuristic for the CVRP” ([DOI](https://doi.org/10.1016/j.cor.2013.10.004)) | Computers & Operations Research 44, 33–41；§2、Algorithm 1 | 并行 TS 线程分工强化/多样化，用 common solution pool 异步交流 | 并行搜索线程、公共解池和信息交换 | 单一目标、TS，不是三代理 HGS；解池不是 route-pool SP 主问题 | 支撑并行合作搜索成熟；不支撑具体主张 |
| He, Hao & Wu (2025 online; 2026 print), “A Hybrid Genetic Algorithm with Multi-population…” ([DOI](https://doi.org/10.1287/ijoc.2023.0416)) | INFORMS Journal on Computing 38(3), 829–843；作者版 §3.2.2 p.12；最终页码映射未核实，需人工复核 | 按 depot configuration 组织多子种群，在各群中做 GA、局部搜索和 mutation | 多子种群并行、混合遗传搜索 | 一个成本函数；无三代理弧成本、无 route-pool SP | 支撑目标层级的多种群先例；不支撑我们的整体新颖 |
| Subramanian, Uchoa & Ochi (2013), “A Hybrid Algorithm for a Class of VRPs” ([DOI](https://doi.org/10.1016/j.cor.2013.01.013)) | Computers & Operations Research 40(10), 2519–2531；§§3.1–3.3 作者版 pp.4–7，Algorithm 1 p.6 | ILS 产生 RoutePool，SP 在有限路线列上选覆盖客户的组合，并与 ILS 反馈 | 路线池、路线组合、MIP 主问题和启发式交互 | 单一 ILS 来源，无多视角；SP 精确性限于有限池 | 强力支撑第二层“成熟标准件”；不支撑第一层 |
| Penna, Subramanian, Ochi, Vidal & Prins (2019), “A Hybrid Heuristic for a Broad Class of VRPs with Heterogeneous Fleet” ([DOI](https://doi.org/10.1007/s10479-017-2642-9)) | Annals of Operations Research 273(1–2), 5–74；§1、§4、Algorithms 1–3 | ILS+RVND 产生路线池，SolveSP/MIP 选路线并与搜索交互 | route pool + SP，且适用于丰富异构车队约束 | 无多种群/多代理视角 | 强力支撑第二层；不支撑第一层 |
| Hiermann, Hartl, Puchinger & Vidal (2019), “Routing a Mix of Conventional, Plug-in Hybrid, and Electric Vehicles” ([DOI](https://doi.org/10.1016/j.ejor.2018.06.025)) | European Journal of Operational Research 272(1), 235–248；作者版 §4 pp.4–7，§5 pp.8–9，§6.3 p.13 | 分层燃油/能源路线评价 + HGA/LNS；把搜索历史路线送入 SP 重组 | 能源机制视角、路线池/搜索历史、SP 重组 | 一个 HGA，不是三个独立代理 HGS；采用分层评价和可行/不可行群 | 最接近整体组合；足以击穿“多视角+SP”作为全新原则 |
| Alvarenga, Mateus & de Tomi (2007), “A Genetic and Set Partitioning Two-Phase Approach…” ([DOI](https://doi.org/10.1016/j.cor.2005.07.025)) | Computers & Operations Research 34(6), 1561–1584；摘要方法；具体小节页码未核实，需人工复核 | GA 中间解路线进入集合 T，随后用 CPLEX SP 选路线组合 | GA/搜索路线池 + SP 后处理/重组 | 无多视角；方法细节页码未完全核实 | 补充支撑 route-pool+SP 已有；不作为唯一依据 |
| 陈雨蝶、干宏程、程亮、温金鹏 (2025 online),《双碳背景下复杂冷链物流模型及求解算法》([DOI](https://doi.org/10.12011/SETP2024-2027)) | 《系统工程理论与实践》；网络首发，正式卷页尚未分配；§3.2 步骤2、4–7，内部 PDF pp.8–9 | 多种群独立进化、迁移、不同交叉/变异概率和 VNS | 多种群并行、混合搜索、目标期刊表达相邻 | 无三代理成本、无 route-pool SP | 说明目标期刊接受相邻结构；不支撑我们的机制新颖 |

## 6. 明确判定

**【有文献支持，但我们做的就是已有做法的改名，不构成贡献点】**

理由是三层证据合在一起的结果，而不是因为找到了完全同构的单篇论文。第一层已经有 Berger (2004)、Lahrichi et al. (2015)、Zhou et al. (2018)、He et al. (2025 online/2026 print) 等高质量先例，说明并行多种群、不同评价信号和精英交换是成熟思想；Vidal (2012, 2014) 说明 HGS 的种群/属性感知评价也有成熟血统。第二层的 route pool + set partitioning 更明确是成熟混合求解标准件，Subramanian (2013)、Penna et al. (2019) 和 Hiermann et al. (2019) 都给出了可核实的路线池—主问题流程。第三层中，Hiermann et al. (2019) 已经在能源车辆 VRP 中把机制相关的分层路线评价、搜索、搜索历史路线和 SP 重组放在同一方法框架内。

因此，“三个代理 HGS”这个具体实例可以是本项目的实现组织方式或应用设定，但仅凭它与 route-pool SP 的组合，不能作为独立算法贡献。把视角数量从两个/多个改成三个，把代理写成燃油、线性电能和非线性充电碳，不足以越过“已有并行多评价搜索 + 已有路线池精确重组”的新颖性门槛。由于本任务严格停止在文献取证，没有对任何性能效果做归因，也没有提出替代算法。

如果审稿人只用一篇论文击倒这个贡献点，那篇是 **Hiermann, Hartl, Puchinger & Vidal (2019), “Routing a Mix of Conventional, Plug-in Hybrid, and Electric Vehicles,” European Journal of Operational Research, 272(1), 235–248**：**“已有工作已经在能源车辆 VRP 中使用机制相关的分层路线评价和高质量搜索，并把搜索历史路线交给集合划分重组；把同一类视角拆成三个代理 HGS 再接 route-pool SP，是并行化和代理重命名，不是新的搜索—重组原则。”** 这句话击倒的是“多视角 + 精确重组作为整体原则的新颖性”，不是声称该论文与三个独立 HGS 的每一行实现完全相同；两者的实现差异已在上文明确列出。

## 7. 顺带发现

- 内部阶段收口记录显示，早期 PyVRP 代理搜索存在与逐仓车队上限不一致的候选过滤问题，且正式科学搜索边界当时仍是关闭状态；因此，现有运行记录不能反过来证明“多视角有效”，本报告也没有把运行表现当作文献证据。见 [mv_hgs_sp_stage1_closeout_20260720.md](../memory/mv_hgs_sp_stage1_closeout_20260720.md#L3-L9)。
- 内部文献审查已经把“search + route pool”列为有先例的混合结构，并把具体三视角接线标成“新颖性尚未由性能门证明”；这与本次外部文献结论一致。见 [e2_order_changing_hybrid_literature_review_20260725.md](../e2_order_changing_hybrid_literature_review_20260725.md#L37-L48) 和 [algorithm_source_and_license_register_20260719.md](../memory/algorithm_source_and_license_register_20260719.md#L79-L82)。
- 当前内部 route-pool 诊断曾出现路线池列很多但新列未被集合划分选中、严格改进为零的记录；这是实现/证据线索，不改变本报告关于文献成熟性的判定。见 [e2_route_column_direct_stop_root_cause_20260725.md](../e2_route_column_direct_stop_root_cause_20260725.md#L8-L17)。
- “精确重组”必须限定为有限 route pool 上的集合划分；time-limited MIP 的 incumbent 不能写成对完整路线空间的全局最优。这是第二层组件的边界。
- 目标期刊相邻文章《双碳背景下复杂冷链物流模型及求解算法》目前是网络首发，正式卷期页码未分配；本报告使用打印 PDF 页和 §3.2 节号，未把未核实页码补成正式页码。
