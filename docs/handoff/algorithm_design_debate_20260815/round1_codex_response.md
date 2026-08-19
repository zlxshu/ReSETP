ROUND1_CODEX_RESPONSE

# 设计对撞·第一轮——Codex 应辩

本轮只做了文档、只读代码核对和联网文献检索；没有运行求解器，没有改算例，也没有改三个受保护文件。文中的 `FACT` 是文件或网页直接支持的事实，`INFERENCE` 是由事实推出的判断，`DECISION` 是本轮建议，`让步` 表示对甲方主张的明确接受。

## 一、第一优先：充电缺口的完整调用链

### 结论

**结论：充电缺口进罚分无须动受保护文件，路径为：提案/交叉 → `charging.py` 预筛或修复 → `education.py` / combat 捕获并保留最好努力状态 → 不受保护的 `algorithms/problem_hgs/evaluation.py` 装配带缺口的 `Solution` 与类型化 `Violation` → `check.py` 返回违规列表 → 现有罚分与双子种群接收。**

这里有一个必须分开的事实：当前代码把失败的 `DutyIndividual` 在物化前丢掉，所以它现在不会自然地到达 `check.py`；如果把同一个不完整 Duty 原样送进当前完整评价，它仍可能在排程物化阶段抛错。无须修改受保护文件的含义是：把“异常退出”改成“最好努力解＋缺口记录”的适配动作，放在不受保护的充电/评价装配层完成。

### 1. Education 链：谁抛、谁接、在哪里丢弃

1. `ChargingRepairFailure` 在 `solver/src/setp_solver/algorithms/problem_hgs/charging.py:152-169` 定义，并继承 `ValueError`。它保留 `duty_id`、原始原因和 `charging_rejection_reason_code`。

2. 预筛入口是 `charging.py:209-217`。它遍历发生变化的实体车及其趟次（`charging.py:228-241`）；一旦 `_screen_trip` 返回确定性失败，就在 `charging.py:246-261` 包装为 `ChargingRepairFailure`、登记拒绝并返回。这个分支没有产生可评价 Duty。

3. 预筛通过后，`repair_changed_duties` 在 `charging.py:530-540` 开始重建变化实体车的 EV 充电账；对 EV 调用 `_repair_one_ev_duty` 或缓存修复（`charging.py:605-624`）。修复内部任何 `TypeError` 或 `ValueError` 在 `charging.py:625-630` 被重新包装为 `ChargingRepairFailure` 后抛出。

4. Education 先处理预筛失败：`education.py:214-228` 收到 failure 后调用 `_rejection`，状态是 `REJECTED_CHARGING`。修复失败则在 `education.py:229-245` 捕获异常，同样返回 `REJECTED_CHARGING`。所以候选在这一层被丢弃，充电缺口尚未成为评价器的违规条目。

5. 如果修复成功，候选才进入增量评价：`education.py:255-266` 调用 `evaluate_after_change`；这里发生的接口型 `TypeError`/`ValueError` 在 `education.py:301-307` 被标成 `REJECTED_INTERFACE`，正常结果在 `education.py:308-316` 标成 `EVALUATED`。

这与当前事实源的概括一致：`education.py:204-238` 的预筛失败或修复异常会把候选记成 `REJECTED_CHARGING`，充电违约目前不进罚分（`docs/handoff/CURRENT_PROJECT_CONTEXT.md:1009-1012`）。

### 2. Combat 链：交叉后在哪里被截断

1. Combat 的交叉结果先在 `integrated_private.py:493-505` 调用 `repair_changed_duties`。

2. 充电修复异常在 `integrated_private.py:506-553` 被捕获。若没有可用的调度交叉修复回退，代码增加拒绝计数、登记 `rejection_reasons`，对包含 `charg`、`battery`、`energy` 或 `soc` 的错误发出 schedule capture，然后 `reject(error)` 并 `continue`（`integrated_private.py:532-554`）。这就是 combat 路径的实际丢弃点。

3. 只有修复成功的候选才会在 `integrated_private.py:555-566` 发出 capture、调用 `evaluate(completed)`。因此现有 `duty_crossover` 的 0 接受不能直接解释为“评价器罚分后仍不胜出”，因为很多后代在完整评价前已经被异常路径截断。A2 的记录是交叉 288 个提案、2 个进入评价、0 个接受，且 63 个被拒交叉后代的原因码全为 `NO_FEASIBLE_WINDOW`；这些数字见 `docs/handoff/CURRENT_PROJECT_CONTEXT.md:32-36` 及甲方辩词 `round1_claude.md:15-20`。

### 3. “最好努力 Duty”送入完整评价时，`check.py` 会怎样

#### 当前原样送入：先抛，尚未到 `check.py`

`DutyEvaluator.evaluate` 在 `algorithms/problem_hgs/evaluation.py:440-441` 进入 `_evaluate_full`；静态路径先在 `evaluation.py:449-465` 做客户分区校验、`individual.to_solution()` 和 `prepare_multitrip_solution(...)`。后者会构造实体车的多趟排程与充电账，而不是直接把不完整 Duty 交给检查器。

排程层的明确失败点是 `multitrip_schedule.py:2473-2493`：遇到没有合法充电缺口、或 `latest < earliest` 时抛出 `ValueError`。所以，**如果“最好努力 Duty”只是缺少合法充电动作，仍以当前 Duty→排程路径原样送入，答案是先抛异常，不是由 `check.py` 记一条 violation。**

#### 先在不受保护层物化成 `Solution`：检查器追加 violation

`check.py:98-107` 的 `check_solution` 初始化 `violations` 列表并返回 `list[Violation]`；它不是异常型布尔门。

- 充电造成的晚到在 `check.py:780-807` 追加 `TIME_WINDOW`；
- EV 路由进入 `check.py:164-186` 的充电功率和电池检查；
- 缺少充电功率、零占用却有正电量、曲线或平均功率超限，在 `check.py:949-1011` 追加 `CHARGING_POWER`；
- 电池沿弧变成负数，在 `check.py:1071-1083` 追加 `BATTERY`，而不是抛异常；充电后超过容量也在 `check.py:1091-1101` 追加 `BATTERY`。

完整评价在 `algorithms/problem_hgs/evaluation.py:537-569` 调用 `check_solution`，随后在 `evaluation.py:631-650` 把违规条目和违规幅度放进 `FullEvaluation`。因此需要增加的不是 protected `search/evaluation.py` 的新罚分机器，而是一个不受保护的装配适配：捕获充电修复失败，保留可转换的路线/实体车状态，把缺口编码为已有 `TIME_WINDOW`、`CHARGING_POWER`、`BATTERY`，或在 `problem_hgs/evaluation.py` 附加一个类型化违规条目。

通用路线评价也已经证明“检查—计罚”链条存在：受保护的 `search/evaluation.py:87-90` 进入 `_penalized_obj`，在 `search/evaluation.py:105-120` 调 `check_solution`、按违规数乘 `BIG_M`、记录 `feasible`。私有 Duty 的实际入口则是上面所列的不受保护 `algorithms/problem_hgs/evaluation.py`，不需要去改受保护文件才能复用这条逻辑。

### 4. 这条结论对两案的影响

`population.py:140-201` 的 `AdaptivePenaltyManager` 对违规类型字符串注册、计数和按幅度计成本；`population.py:204-235` 按 `evaluation.feasible` 把候选分到可行/不可行子种群。甲方在 `round1_claude.md:28-42` 对这两点的逐行核对成立。

**INFERENCE：** 甲乙两案在“缺口如何越过异常边界”这一施工入口上已经合并；分歧不再是“是否要另造罚分机器”，而是“最好努力解在不受保护评价装配层怎样被物化，以及缺口用已有类型还是附加类型表示”。

**DECISION：** 本轮不主张改 `search/evaluation.py`、`check.py` 或 `cost.py`。先在不受保护层完成“捕获—物化—完整评价—罚分”的最小链，并单独报告缺口类型、幅度、候选是否进入评价和是否进入种群。

## 二、回应攻击 1：采纳 G1，把真约束前移到提案域

### 结论

**采纳。G1 放在主体提案域层，先于路线交叉、局部搜索和充电修复；它不是评价器事后补罚，也不是充电修复器的替代品。**

甲方给出的 A2 数字是 22,813 个提案中预筛拒 14,222 个，比例 62.3%（`round1_claude.md:55-58`；当前事实源同样记录于 `CURRENT_PROJECT_CONTEXT.md:33`）。这足以证明提案域和真实容量/班次约束之间存在接线问题；不需要再为“不采纳”找理由。

代码上，两个开关确实存在但默认关闭：`kernel_proposals.py:45-60` 中 `rebuilt_volume_capacity_enabled=False`、`rebuilt_shift_neighbours_only=False`。开关状态在 `kernel_proposals.py:61-84` 保存，并在 `kernel_proposals.py:102-114` 传入唯一资产问题构造器。

它们不是空开关：

- `kernel_proposals.py:617-643` 从已登记的 route contract 读取客户体积和车辆体积容量并缩放；
- `kernel_proposals.py:679-695` 把需求、体积、车场锁定和车型锁定组装进提案模型；
- `kernel_proposals.py:136-137` 在班次邻域开关打开时收缩邻居，`:193-204,244-248` 把同班次邻居开关写入算子身份；`dynamic_insertion.py:257-268` 已经按 route contract 传递体积/班次相关标志。

### 验收方式

1. 在不改评价口径的前提下，冻结同一输入和同一提案随机流，只核对配置是否真的把 `include_rebuilt_volume_capacity` 与班次邻域设置传进提案构造器；这一步是接线核验，不是正式结果。

2. 对每个提案保留现有通道计数和预筛原因，额外核对提案生成时的体积与班次约束是否来自同一 route contract，而不是从默认值或后处理补回来。证据位置是 `kernel_proposals.py:617-643`、`:679-695`。

3. 继续使用现有的 `proposed → prescreen → repair → evaluated → accepted` 计数，且同时核对服务客户数和需求量。当前铁律要求完整解报告 50/50 客户和 13264/13264 kg（`CURRENT_PROJECT_CONTEXT.md:33,521-522`）；G1 生效不能以少服务换取更低成本。

4. G1 的第一验收问题是“提案域是否真的带了体积/班次约束”，不是预先自设一个接受率或效果阈值。吞吐和搜索效果作为后续实测分别记录，不能把实现接线直接写成算法收益。

**DECISION：** 原来的串行链补成 `G1 真约束提案域 → 路线/多趟交叉 → 充电修复或缺口捕获 → 完整评价`。G1 不取代第一节的缺口捕获，两者解决的是提案生来不合法和候选物化失败两个不同位置的问题。

## 三、回应攻击 2：择时通道的 20 分钟诊断与退役判据

### 结论

**不根据“0 接受”四个字直接删掉择时代码；先做一次 20 分钟内的归因探针。若证实它确实能进入完整评价但没有任何现有接受规则下的改进，再退役为独立提案通道，保留补全栈内的择时策略。**

A1 与 A2 的现有记录分别有 1,775 和 1,289 个择时提案，均进入评价但均为 0 接受，合计 3,064/0（`solver/reports/design_probe_death_survey2_20260815/report.md:24,66`；甲方辩词 `round1_claude.md:60-63`）。这已经排除了“所有提案都在预筛前死掉”这一种解释，但还没有区分经济上不值得、候选没有实际改变、还是接受接线有问题。

### 事先冻结的诊断设计（总墙钟不超过 20 分钟）

1. 固定现有 A1/A2 的输入、父代、随机流和评价器；不改碳价、不改目标、不加预算、不换算例。诊断对象只允许改变同一充电安排的时间位置，路线、客户分配、车场、车型、趟次和充电量保持不变。

2. 逐条记录现有择时提案的五个节点：`proposed`、`prescreen`、`repair`、`evaluated`、`accepted`。对每条进入评价的候选记录父代与子代的充电开始时间、总成本、电费、碳成本、总评价值，以及“子代实际上没有变化”的标记。

3. 对所有进入完整评价的候选，使用现有接受谓词逐条重算，不另设接受阈值。这里要看的不是只剩 0 这个计数，而是 `evaluated` 候选是否存在严格改善、改善来自电价还是碳价、以及改善是否在接受环节丢失。

4. 20 分钟到点即停，保存逐候选表和通道计数。没有跑完不把“未观测到接受”写成退役结论；只报告已经走到哪一个节点。

### 事先写死的退役判据

- **退役独立择时提案通道：** 在 20 分钟窗口内有 `evaluated > 0`；所有实际改变了时间位置的已评价候选都没有低于父代的现有总评价值；并且 `accepted = 0`。此时把择时从竞争性 proposal channel 退役，代码保留，择时仍由充电补全栈和碳价情景承担。
- **不退役，转查接线：** 存在已评价且低于父代的候选但 `accepted = 0`。这说明接受路径或账目比较有问题，不能把它判为择时无效。
- **不退役，转查上游：** `evaluated = 0`，或实际改变时间位置的候选在 repair 前全部失败。此时问题是提案域、修复或物化，不是择时经济价值。
- **保留通道：** 出现至少一条按现有接受谓词被接受的候选；再另做多种子方向验证。

**DECISION：** 这套判据把“通道无效”“候选没有真正改变”“接受链断了”分开。若第一种成立，我接受甲方的退役主张；在诊断完成前，只能说“现有 3,064 个已评价择时提案没有接受”，不能把经济解释提前写死。

## 四、强制攻击 1：路线层交叉如何恢复多趟、实体车身份和跨趟 SOC

### 结论与让步

**让步：** 如果“降到路线层”只意味着把客户序列交叉后直接拼回匿名路线集合，那么它确实不能恢复本项目要求的实体车身份、最多三趟的顺序和跨趟 SOC。路线层交叉必须后接“趟次/实体车解码＋充电/SOC 重物化”；不能只改 `crossover.py` 的一处字符串表示。

**不让步的部分：** 这并不推翻路线层交叉，而是规定它的接口。文献和实现中已经有“路线序列/巨型路线 → 趟次分割或标签 → 车辆分配 → 充电/可行性解码”的做法；本项目还必须把解码结果装回现有 `PhysicalVehicleDuty` 和 `ScheduledDuty` 契约。

### 至少两条有出处的多趟交叉/表示方案

#### 方案 A：巨型路线＋Split，把一条排列切成多趟解

FACT：Cattaruzza、Absi、Feillet、Vidal（2014），*The Multi-Trip Vehicle Routing Problem with Time Windows*，**European Journal of Operational Research 236(3):833-848**，DOI `10.1016/j.ejor.2013.06.012`。出版社页面明确把 MTVRP 定义为车辆一天执行多趟，并说明混合遗传算法用 Split 程序把染色体分割成多趟解；文献入口：[ScienceDirect](https://www.sciencedirect.com/science/article/pii/S0377221713005006)。

这里的可迁移点是：交叉在客户排列上工作，Split 决定车辆趟次边界；不是把已经带有完整充电账的 Duty 直接互换。它能解决“客户排列如何切成多趟”的问题，但原论文的 MTVRP 表示不能自动证明本项目的实体车 ID 与跨趟电池状态都被保留。这一限制是本项目接口必须补上的部分。

#### 方案 B：车辆分配＋趟次分隔符＋专用 MultiTripRBX

FACT：HeuristicLab 官方 VRP 编码文档说明，`MultiTripEncoding` 从保存车辆分配的 `PotvinEncoding` 扩展，并额外保存 tour delimiters（官方仓库文档行 53-58）；其 `MultiTripRBX` 先执行路线交叉，再把被复制 tour 的分隔符复制到被替换 tour（行 478-538）。同一文档明确指出普通 Potvin 交叉会忽略 trip delimiters，需专用多趟交叉（行 567-568）。来源：[HeuristicLab Implement a New VRP Encoding](https://dev.heuristiclab.com/trac.fcgi/wiki/Documentation/Howto/ImplementANewVRPEncoding)。

这条方案直接回答了本轮攻击：路线交叉可以保留，但交叉对象必须带车辆分配和趟次边界；分隔符不能交给普通单趟 OX 随意丢掉。这里的“车辆分配”是恢复实体车身份的接口，不是事后让一个匿名解码器随意重排车。

#### 方案 C：巨型路线＋labeling procedure，把分段与时间窗一起解码

FACT：Cattaruzza、Absi、Feillet（2016），*The Multi-Trip VRP with Time Windows and Release Dates*，**Transportation Science 50(2):676-693**，DOI `10.1287/trsc.2015.0608`。INFORMS 页面说明其 population algorithm 使用 giant-tour representation，再由 labeling procedure 转成多趟解（官方页面行 217-220；书目信息行 255-264）。来源：[INFORMS](https://pubsonline.informs.org/doi/abs/10.1287/trsc.2015.0608?journalCode=trsc)。

它说明“路线染色体不等于最终排程”：趟次、时间窗和释放条件可以作为解码阶段的问题求解。对本项目而言，labeling/解码阶段还要读取实体车注册表和上一个趟次的 SOC，不能只返回成本最小的匿名标签。

### 在本项目中恢复三个约束的具体接口

1. **路线层的染色体内容：** 客户排列可以作为主交叉内容；同时保留趟次分隔符，或保留每段到实体车的绑定。方案 A 适合“巨型路线＋Split”，方案 B 适合“车辆分配＋分隔符＋专用交叉”。不允许把 `EV_001#T1` 和 `EV_002#T2` 当成没有共同身份的两条普通路线。

2. **实体车身份、车型和车场：** `DutyIndividual.to_solution` 在 `model.py:492-525` 用实体车 ID、车型、home depot 和趟次生成 route/action；`model.py:328-400` 的 `PhysicalVehicleDuty` 强制 ID 前缀、车型/车场一致和趟次从 1 连续。由路线层产生的子代必须经这个契约重新分组，而不是绕过它。

3. **多趟顺序：** `model.py:528-620` 的 `from_solution` 按物理车基 ID 和 `#T` 后缀分组、排序，混合车型或 home depot 会拒绝。解码器应在这里恢复趟次序；如果交叉后分隔符不连续，先返回类型化结构缺口，不把非法趟序静默修成另一辆车。

4. **跨趟 SOC：** 每辆 EV 的充电安排由第一趟结束状态传给下一趟开始状态，再由充电补全器重建。现有 `ScheduledDuty` 在 `model.py:271-303` 强制 SOC 事件索引连续，并要求相邻事件满足 `left.soc_after_kwh == right.soc_before_kwh`（容差 `1e-7`）。这是交叉后必须复核的接口，不是染色体层可以省掉的字段。

5. **充电缺口：** 交叉后对已改变实体车丢弃其未锁定旧充电账，调用现有充电补全；补全成功则生成新的 charging sessions，补全失败则按第一节在不受保护的装配层保留最好努力路线和类型化缺口，再进入完整评价。这样路线层交叉不会偷偷复用与新趟次不匹配的 SOC 账。

6. **验收记录：** 对每个后代至少记录客户 exact cover、实体车 ID、车型、home depot、连续趟次、跨趟 SOC、充电动作、完整评价和 violation 类型。当前事实源确认完整评价本来就覆盖这些字段（`CURRENT_PROJECT_CONTEXT.md:519-522`），所以这里是把现有契约接回路线交叉，不是新造一个平行评价器。

**UNKNOWN：** 本次检索没有找到一篇同时完全采用“本项目的实体车 ID、两车场、每车最多 3 趟、跨趟连续 SOC、充电窗口缺口”这五个约束的现成交叉实现。因此上面关于解码器与本项目 Duty 契约的连接是工程设计，不冒充文献已经替我们证明。

## 五、强制攻击 2：B0 不含交叉，还算不算标准 HGS 适配

### 结论与让步

**让步：B0 不含交叉，不应在论文中称为“标准 HGS 适配”。** 更准确的名称是“禁用交叉的 HGS-derived baseline”或“无交叉 HGS 框架基线”。它可以作为组件增量的内部分母，但不能把 B0 的名字写成完整 HGS。

FACT：Vidal（2020），*Hybrid Genetic Search for the CVRP: Open-Source Implementation and Data Sets*，技术报告第 2-4 页，明确把 HGS 组成写成交叉用于多样化、局部搜索用于改进，并在每轮选择两个父代、重组后代、局部搜索和回插种群；其 OX＋Split 结构见第 3-4 页。来源：[HGS-CVRP technical report](https://w1.cirrelt.ca/~vidalt/papers/HGS-CVRP-2020.pdf)。

FACT：PyVRP 官方 HGS 介绍的伪代码也把 `Select parents → Apply crossover → Improve by LS → Add offspring` 列为循环骨架（官方页面行 46-66）。来源：[PyVRP Introduction to HGS](https://pyvrp.github.io/v0.11.0/setup/introduction_to_hgs.html)。

因此，关掉交叉后仍可以保留 HGS 的罚分、局部搜索、可行/不可行种群等框架，但它已经是受控的“crossover-disabled”变体。消融表可以把它作为分母，前提是所有表题、图例和方法段落都明确写“禁用交叉”，不把结果包装成标准 HGS 的结果。若要有一个标准 HGS 对照，必须另外打开并记录一条合法的标准交叉链；这不是用 B0 的名称偷补出来的。

## 六、参考文献 2 更正

**CORRECTION：** 参考文献 2 应写为：

金东遥，刘敏，朱烨娜，赵肄江．基于混合遗传搜索求解载重约束的电动车辆路径问题．**系统仿真学报，2024，36(11)：2528-2541**．DOI：**10.16182/j.issn1004731x.joss.23-0863**。

出版社书目页核对了卷期、页码和 DOI：[Journal of System Simulation, 36(11), 2528-2541](https://dc-china-simulation.researchcommons.org/journal/vol36/iss11/3/)。原文 PDF 入口：[official PDF](https://www.china-simulation.com/EN/article/downloadArticleFile.do?attachType=PDF&id=3512)。

这一文献可支持“路线层与固定路线充电子问题分开”的表示启发，但它不能替代本项目对实体车身份和跨趟 SOC 的本地契约核验；这一点与第四节的 `UNKNOWN` 边界一致。

## 七、对三案骨架的逐案表态

### 甲案：生成优先

**表态：同意作为候选收敛起点，但修改两处。**

甲案的 G1＋路线层交叉＋缺口捕获方向成立：G1 的两个开关已经存在且能把体积、车场/车型锁定信息送入提案域（`kernel_proposals.py:45-114,617-695`）；多趟文献也支持“路线表示后接 Split/labeling/专用交叉”（本答辩第四节）。

必须修改的是：

1. “路线层交叉”不能只施工成 `crossover.py` 的客户序列操作，必须明确车辆分配/趟次分隔符和 Duty 解码接口；否则 `model.py:328-400` 的实体车与趟次契约没有恢复路径。
2. 缺口捕获不能只记日志。它要在不受保护的评价装配层生成可检查的最好努力 `Solution` 或附加类型化违规；否则仍会在 `evaluation.py:452-465` 的排程物化处抛错。

**DECISION：** 甲案可以进入施工排序，但它的验收对象是“后代能带着身份、趟次和 SOC 走到完整评价”，不是只看交叉提案数。

### 乙案：评价优先

**表态：同意作为本轮最小收敛起点，并把 G1 放到它之前。**

第一节的静态证据表明，现有罚分机器和双子种群已经存在，真正缺口是充电异常在进入评价前被硬拒绝；`problem_hgs/evaluation.py` 又不在受保护清单（`round1_claude.md:28-42`）。因此先做“最好努力解＋缺口捕获＋完整评价”能以较小的施工面验证架构事实。

修改意见有两点：

1. G1 不是乙案之后才补的附加零件。它位于提案域入口，必须先完成开关有效性核对；A2 预筛拒 62.3% 的事实不能留在乙案之外。
2. 乙案第一轮不能把“进入罚分”直接写成算法收益。要逐条区分“进入评价”“进入不可行子种群”“被接受”，并同时报服务客户数和需求量；当前 `CURRENT_PROJECT_CONTEXT.md:33,519-522` 已给出这一记录边界。

**DECISION：** 施工顺序建议为 `G1 接线核对 → 缺口捕获与完整评价 → 再决定是否启用竞争性路线交叉`。这不是把路线层交叉否决，而是先让评价链具备接住后代的能力。

### 丙案：两者合并

**表态：不作为第一步起点；保留为第二阶段的合并候选。**

丙案最终可能是完整方案：G1 收窄提案域，路线层交叉产生新客户排列，实体车/趟次解码恢复 Duty，充电缺口进入完整评价，罚分与双子种群完成搜索反馈。但现在同时改生成域、交叉层、充电异常边界和评价路径，会让“接受数变化”无法归因于某一个结构修复。

这个顺序判断有当前证据支撑：A2 已有 22,813 提案、62.3% 预筛拒，且 349.7 秒只覆盖 2 循环（`CURRENT_PROJECT_CONTEXT.md:33`）；交叉则是 288→2→0，63/63 后代同一充电窗死因（同上及 `round1_claude.md:15-20`）。这些事实足以说明丙案应拆成可归因的两步，尚不足以证明丙案本身错误。

**DECISION：** 丙案的保留条件不是代理自设的科学门槛，而是两个子链都要留下可复核的中间证据：G1 实际进入提案域；路线/实体车/SOC 解码后的候选能进入完整评价；充电缺口能被记录并计罚。满足后再合并，论文才有资格把它作为一条完整算法链来叙述。

## 八、本轮最终裁决与边界

1. 充电硬拒绝的病灶在 `charging.py`/教育与 combat 的异常边界，不在受保护罚分文件；本轮裁决是先走不受保护的“最好努力解＋类型化缺口＋完整评价”路径。
2. G1 采纳，位置是主体提案域入口；62.3% 的 A2 预筛拒绝作为现状证据保留。
3. 择时通道先按第三节的 20 分钟诊断；满足退役判据时退役独立提案通道，保留补全栈策略。
4. 路线层交叉必须配套多趟/实体车/SOC 解码；只做客户序列交叉不够。
5. B0 无交叉可以作为内部消融分母，但不称“标准 HGS 适配”。
6. 本轮没有把任何建议写成用户已决，也没有把探针、设计或上界写成正式实验结果。
