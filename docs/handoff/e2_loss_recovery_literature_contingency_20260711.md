# E2负例恢复：文献依据与失败后备路线（2026-07-11）

状态：`PREPARED_ONLY / DO_NOT_EXECUTE_WHILE_PROPORTIONAL_GATE_IS_RUNNING`

## 人话判决

当前把1600评价按160/1280/160分配，不是为了临时调出好数字。正式4000算法本来就是400/3200/400，也就是10%开头、80%核心搜索、10%收尾。上一短门固定拿走800次做两侧阶段，使真正LNS核心只剩一半预算；新门只是让短门忠实模拟正式算法。

这种“按总时间或总预算调整各搜索模块占比”的做法有成熟文献依据。Graf（2020）的ALNS+VND方法专门用自适应层根据实例、时间限制和机器速度分配搜索资源，并指出短时间下不能把预算浪费在不合时宜的探索或强化上。当前10/80/10是最克制的静态版本：不根据已看到的结果调实例，不增加评价，不改变LNS或referee。

## 当前门若通过

只进入未见种子4000评价验证。不得直接把开发种子的短门结果写进论文，也不得立刻重跑全量。4000时比例候选与正式400/3200/400完全相同，因此不再引入新的阶段参数。

## 当前门若失败

true-LNS路线结束，不再继续调10%、15%、20%等比例。下一步先在现有保存解上做结构诊断，再由以下成熟路线二选一；没有证据时不施工。

第一候选是“时间/实例感知的分层调度”，来源是Graf（2020）的ALNS+VND自适应层。它不是再扫固定比例，而是依据剩余预算、实际迭代速度和阶段改进率决定继续LNS还是返回ALNS。启动前必须先用现有history证明阶段改进率能预测后续收益，否则不做。

第二候选是HGS式路线级重组。Vidal（2022）的开源HGS和PyVRP使用种群、多样性、路线交换交叉与局部搜索；SREX直接交换父代路线，SWAP*强化跨路线重组。这条路线与当前11个负例“路线数更多”的病灶相符，但接入ReSETP的多车场、车型、充电和多趟语义工作量明显更大。只有当短门失败且route-signature审计证明不同运行间存在可互补的优质路线块时，才允许做headroom；不得直接移植整套HGS。

不再尝试的路线包括：继续调重启间隔、再次微调selector、恢复历史`RELAXED_ROUTE_COMPRESSION`、重新叠加旧route-pool/RVND补丁、只改接受准则。Santini、Røpke与Hvattum（2018）确实表明RRT、SA和threshold acceptance中有强方案，但本项目历史RRT单变量已经明显退化；没有新失败条件，不重复跑。

## 主要来源

- Graf, B. (2020). Adaptive large variable neighborhood search for a multiperiod vehicle and technician routing problem. *Networks, 76*, 256–272. https://doi.org/10.1002/net.21959
- Vidal, T. (2022). Hybrid genetic search for the CVRP: Open-source implementation and SWAP* neighborhood. *Computers & Operations Research, 140*, 105643. https://doi.org/10.1016/j.cor.2021.105643
- PyVRP contributors. A brief introduction to HGS and SREX crossover documentation. https://pyvrp.github.io/v0.11.0/setup/introduction_to_hgs.html and https://pyvrp.readthedocs.io/en/latest/api/crossover.html
- Santini, A., Røpke, S., & Hvattum, L. M. (2018). A comparison of acceptance criteria for the adaptive large neighbourhood search metaheuristic. *Journal of Heuristics, 24*(5), 783–815. https://doi.org/10.1007/s10732-018-9377-x

## 约束

当前比例短门完成以前，本文件只作为后备判断依据，不授权新代码、新实验或全量。任何后备候选仍须同预算、正式起点、零违规、保存解复算、先短门后未见种子；不得修改`cost.py`、`check.py`、`search/evaluation.py`、价格、物理约束或算例。
