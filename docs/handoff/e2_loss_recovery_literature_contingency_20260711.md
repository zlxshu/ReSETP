# E2负例恢复：文献依据与失败后备路线（2026-07-11）

状态：`ROUTE_SIGNATURE_AUDIT_NEGATIVE / HGS_SREX_NOT_AUTHORIZED / CLOSED`

## 人话判决

当前把1600评价按160/1280/160分配，不是为了临时调出好数字。正式4000算法本来就是400/3200/400，也就是10%开头、80%核心搜索、10%收尾。上一短门固定拿走800次做两侧阶段，使真正LNS核心只剩一半预算；新门只是让短门忠实模拟正式算法。

这种“按总时间或总预算调整各搜索模块占比”的做法有成熟文献依据。Graf（2020）的ALNS+VND方法专门用自适应层根据实例、时间限制和机器速度分配搜索资源，并指出短时间下不能把预算浪费在不合时宜的探索或强化上。当前10/80/10是最克制的静态版本：不根据已看到的结果调实例，不增加评价，不改变LNS或referee。

## 当前门若通过

只进入未见种子4000评价验证。不得直接把开发种子的短门结果写进论文，也不得立刻重跑全量。4000时比例候选与正式400/3200/400完全相同，因此不再引入新的阶段参数。

## 当前门若失败

true-LNS路线结束，不再继续调10%、15%、20%等比例。下一步先在现有保存解上做结构诊断，再由以下成熟路线二选一；没有证据时不施工。

2026-07-11实际结果已确认该条件触发：比例候选全部样本平均退化0.329%、只转回1个负例、最差保护样本退化3.005%。阶段比例调整已关闭，当前只执行不新跑搜索的route-signature互补性审计。

后续审计也已完成：6/6开发负例存在可行混合整路块组合，但0/6对当组最好父解有至少0.25%改善，0/6多救回负例。这不满足本文档规定的HGS/SREX施工前提，因此不移植种群搜索或SWAP*，E2恢复到此关闭。

## 最终开源与论文复核

2026-07-11在关闭前又做了一次源码、开源库和本地Zotero文献的交叉复核。结论不是“数学上绝对无解”，而是“当前没有同预算、短周期、可公平写入论文的救援方案”。

Vidal的HGS-CVRP确实用种群、多样性管理、交叉和完整SWAP*产生新路线，PyVRP的SREX也能交换父代整路块。但HGS-CVRP的公开实现主要面向标准CVRP；PyVRP虽支持多车场、异质车队、时间窗和多趟/重装，但它的公开功能不直接覆盖ReSETP的电量连续性、充电站时段容量、充电碳排和当前多趟合同。SREX还可能产生不完整子代，必须再做项目特定修复。因此这不是换一个函数，而是新建一条求解器研发线。

本地Zotero中最接近的工作也支持这个判断。Hiermann等的混合油车、插混和电车HGA使用种群多样性、局部/大邻域、路线历史集合划分，并为每条路线另做充电/燃料决策的分层评估；多车场绿色VRP的VNS也同时使用多类跨路线交换和充电站add/drop/swap。这些论文证明“更强方法理论上可能继续改善”，也同时证明它需要一整套路线生成、充电评估、种群管理和修复机制，不是E2收尾阶段的小补丁。

本仓库已有的`SETP_ALNS_CRUSH_RVND_SWAPSTAR`不能作为捷径。其`_swapstar_lite_neighbors()`只在两条路线的原位置交换客户，没有实现Vidal SWAP*“分别寻找最佳重插位置”的关键机制；当前relocate、swap-lite和2-opt-star也都不能直接消掉一条路线，与11/15负例“路线数更多”的主病灶不匹配。更重要的是，它的内部邻居通过`score_reference()`评分，不消耗`EvalBudget`。如果直接打开，它会在4000评价口径外做大量完整解评分，即使数字变好也不是公平结果。该开关保持关闭。

如果将来审稿确实要求“每组更强”，可以另立一个长周期方法项目：先实现严格计入预算的完整SWAP*/route elimination，再建立兼容ReSETP物理合同的种群、SREX和修复器。在论文当前进度下，这一项明确不解冻，不因15个负例重开E2。

第一候选是“时间/实例感知的分层调度”，来源是Graf（2020）的ALNS+VND自适应层。它不是再扫固定比例，而是依据剩余预算、实际迭代速度和阶段改进率决定继续LNS还是返回ALNS。启动前必须先用现有history证明阶段改进率能预测后续收益，否则不做。

第二候选是HGS式路线级重组。Vidal（2022）的开源HGS和PyVRP使用种群、多样性、路线交换交叉与局部搜索；SREX直接交换父代路线，SWAP*强化跨路线重组。这条路线与当前11个负例“路线数更多”的病灶相符，但接入ReSETP的多车场、车型、充电和多趟语义工作量明显更大。只有当短门失败且route-signature审计证明不同运行间存在可互补的优质路线块时，才允许做headroom；不得直接移植整套HGS。

不再尝试的路线包括：继续调重启间隔、再次微调selector、恢复历史`RELAXED_ROUTE_COMPRESSION`、重新叠加旧route-pool/RVND补丁、只改接受准则。Santini、Røpke与Hvattum（2018）确实表明RRT、SA和threshold acceptance中有强方案，但本项目历史RRT单变量已经明显退化；没有新失败条件，不重复跑。

## 主要来源

- Graf, B. (2020). Adaptive large variable neighborhood search for a multiperiod vehicle and technician routing problem. *Networks, 76*, 256–272. https://doi.org/10.1002/net.21959
- Vidal, T. (2022). Hybrid genetic search for the CVRP: Open-source implementation and SWAP* neighborhood. *Computers & Operations Research, 140*, 105643. https://doi.org/10.1016/j.cor.2021.105643
- Vidal, T. HGS-CVRP official implementation. https://github.com/vidalt/HGS-CVRP
- PyVRP contributors. A brief introduction to HGS and SREX crossover documentation. https://pyvrp.github.io/v0.11.0/setup/introduction_to_hgs.html and https://pyvrp.readthedocs.io/en/latest/api/crossover.html
- Hiermann, G., Hartl, R. F., Puchinger, J., & Vidal, T. (2019). Routing a mix of conventional, plug-in hybrid, and electric vehicles. *European Journal of Operational Research, 272*(1), 235–248. https://doi.org/10.1016/j.ejor.2018.06.025
- Sadati, M. E. H., & Çatay, B. (2021). A hybrid variable neighborhood search approach for the multi-depot green vehicle routing problem. *Transportation Research Part E, 149*, 102293. https://doi.org/10.1016/j.tre.2021.102293
- Santini, A., Røpke, S., & Hvattum, L. M. (2018). A comparison of acceptance criteria for the adaptive large neighbourhood search metaheuristic. *Journal of Heuristics, 24*(5), 783–815. https://doi.org/10.1007/s10732-018-9377-x

## 约束

当前比例短门完成以前，本文件只作为后备判断依据，不授权新代码、新实验或全量。任何后备候选仍须同预算、正式起点、零违规、保存解复算、先短门后未见种子；不得修改`cost.py`、`check.py`、`search/evaluation.py`、价格、物理约束或算例。
